#!/usr/bin/env python3
"""Entrena los modelos finales (Isolation Forest y Autoencoder) con TODAS las filas normales de una campana
y los guarda en disco para usarlos con detect.py.

Uso:
  python train_final.py data/campaign_<fecha>.csv                      # guarda en models/
  python train_final.py data/campaign_<fecha>.csv --exclude-runs ID1,ID2   # deja runs fuera (para validar con detect.py)

Se entrena solo con filas label=0 de las fases baseline y post (sin warmup ni recovery). El umbral de cada modelo es
el percentil 95 de las puntuaciones FUERA DE MUESTRA sobre esos datos normales (dos mitades de runs, cruzadas), y se
guarda tambien el error tipico por variable en datos normales, que normaliza la explicacion.
"""
import argparse
import json
import os
import platform
import sys
import warnings
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import sklearn

from anomaly_models import MODELS, PCT, Scaler, feature_columns

warnings.filterwarnings("ignore")   # avisos de convergencia de MLPRegressor: se informan abajo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--out", default="models")
    ap.add_argument("--exclude-runs", default="", help="run_id separados por comas que NO se usan para entrenar")
    ap.add_argument("--pct", type=float, default=PCT, help="percentil del umbral (default 0.95)")
    a = ap.parse_args()

    d = pd.read_csv(a.csv)
    for col in ("phase", "label", "run_id", "run_ok"):
        if col not in d.columns:
            sys.exit(f"Falta la columna '{col}': usa un CSV de campana generado por run_campaign.py")
    excl = {s.strip() for s in a.exclude_runs.split(",") if s.strip()}
    unknown = excl - set(d.run_id)
    if unknown:
        sys.exit(f"run_id desconocidos en --exclude-runs: {sorted(unknown)}")
    d = d[d.phase.isin(["baseline", "fault", "post"]) & ~d.run_id.isin(excl) & d.run_ok.ne(False)].copy()
    feat = feature_columns(d)
    d[feat] = d[feat].fillna(0)
    tr = d[d.label == 0].sort_values(["run_id", "timestamp"])
    runs = sorted(tr.run_id.unique())
    print(f"Entrenando con {len(tr)} filas normales de {len(runs)} runs; {len(feat)} features")

    sc = Scaler().fit(tr[feat].values)
    Z = sc.transform(tr[feat].values)
    grp = tr.run_id.map({r: i % 2 for i, r in enumerate(runs)}).values   # mitades de runs, cruzadas
    models, thresholds = {}, {}
    for M in MODELS:
        oof_s, oof_d = np.zeros(len(tr)), np.zeros((len(tr), len(feat)))
        for g in (0, 1):
            m = M().fit(Z[grp != g])
            oof_s[grp == g], oof_d[grp == g] = m.score(Z[grp == g]), m.dev(Z[grp == g])
        thr = float(np.quantile(oof_s, a.pct))
        ref = np.maximum(oof_d.mean(0), 1e-9)
        final = M().fit(Z)
        insample = float((final.score(Z) > thr).mean())
        models[M.name] = dict(model=final, threshold=thr, ref=ref)
        thresholds[M.name] = thr
        print(f"  {M.name:17s} umbral={thr:.4f}  filas de entrenamiento sobre el umbral={100 * insample:.1f}%")
        if hasattr(final, "ms"):
            print("    Autoencoder: perdida final por semilla = "
                  + ", ".join(f"{m.loss_:.4f} ({m.n_iter_} it.)" for m in final.ms)
                  + "  (llega al maximo de 800 iteraciones: la perdida ya casi no mejora)")

    os.makedirs(a.out, exist_ok=True)
    bundle = dict(features=feat, scaler=sc, models=models, pct=a.pct, step_s=5.0,
                  alert_rule="2 filas consecutivas por encima del umbral")
    path = os.path.join(a.out, "model_bundle.joblib")
    joblib.dump(bundle, path, compress=3)
    meta = dict(
        creado=datetime.now().isoformat(timespec="seconds"),
        csv_entrenamiento=os.path.basename(a.csv),
        runs_entrenamiento=runs,
        runs_excluidos=sorted(excl),
        filas_entrenamiento=int(len(tr)),
        features=feat,
        percentil_umbral=a.pct,
        umbrales=thresholds,
        regla_alerta=bundle["alert_rule"],
        versiones=dict(python=platform.python_version(), scikit_learn=sklearn.__version__,
                       numpy=np.__version__, pandas=pd.__version__),
        nota="Los .joblib dependen de la version de scikit-learn: reentrena si cambias de version.",
    )
    json.dump(meta, open(os.path.join(a.out, "metadata.json"), "w"), indent=2, ensure_ascii=False)
    print(f"Guardado: {path} ({os.path.getsize(path) / 1e6:.1f} MB) y metadata.json")


if __name__ == "__main__":
    main()
