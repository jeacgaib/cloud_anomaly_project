#!/usr/bin/env python3
"""Puntua un CSV de metricas con los modelos guardados y explica cada anomalia (servicio y variables).

Uso:
  python detect.py data/<run>_dataset.csv                          # ambos modelos
  python detect.py data/campaign_<fecha>.csv --model autoencoder   # solo uno
Salida:
  <entrada>_detect.csv   una fila por muestra: puntuacion, umbral, marca y evento de cada modelo
  <entrada>_events.csv   un evento por anomalia confirmada, con componente y variables señaladas
El CSV debe tener las mismas columnas de metricas que el de entrenamiento (las produce export_dataset.py).
Un evento = 2 o mas filas consecutivas sobre el umbral. Se ignora la fase warmup si el CSV trae 'phase'.
"""
import argparse
import os
import sys
import warnings
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import sklearn

from anomaly_models import COMPONENTS  # noqa: F401  (necesario para deserializar los modelos)

KEYS = {"autoencoder": "Autoencoder", "isolation_forest": "Isolation Forest"}


def find_events(flag):
    """Devuelve [(inicio, fin)] (indices, fin inclusivo) de secuencias de >= 2 filas marcadas."""
    ev, i, n = [], 0, len(flag)
    while i < n:
        if flag[i]:
            j = i
            while j + 1 < n and flag[j + 1]:
                j += 1
            if j - i + 1 >= 2:
                ev.append((i, j))
            i = j + 1
        else:
            i += 1
    return ev


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--models", default="models", help="carpeta con model_bundle.joblib")
    ap.add_argument("--model", choices=["both", *KEYS], default="both")
    ap.add_argument("--top", type=int, default=3, help="variables a mostrar por evento")
    ap.add_argument("--keep-warmup", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    path = os.path.join(a.models, "model_bundle.joblib")
    if not os.path.exists(path):
        sys.exit(f"No encuentro {path}. Ejecuta primero: python train_final.py data/campaign_<fecha>.csv")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bundle = joblib.load(path)
    feat, sc = bundle["features"], bundle["scaler"]

    df = pd.read_csv(a.csv)
    missing = [c for c in feat if c not in df.columns]
    if missing:
        sys.exit(f"Al CSV le faltan columnas que usan los modelos: {missing}")
    if "phase" in df.columns and not a.keep_warmup:
        df = df[df.phase != "warmup"]
    grp_col = "run_id" if "run_id" in df.columns else None
    sort_cols = ([grp_col] if grp_col else []) + (["timestamp"] if "timestamp" in df.columns else [])
    df = df.sort_values(sort_cols).reset_index(drop=True) if sort_cols else df.reset_index(drop=True)
    X = df[feat].astype(float).fillna(0)   # igual que en train_final.py y evaluate.py
    Z = sc.transform(X.values)
    groups = df[grp_col].values if grp_col else np.zeros(len(df))

    names = list(KEYS.values()) if a.model == "both" else [KEYS[a.model]]
    out = df[[c for c in ("run_id", "timestamp", "phase", "label", "scenario", "severity") if c in df.columns]].copy()
    events = []
    for n in names:
        mdl = bundle["models"][n]
        s = mdl["model"].score(Z)
        ratio = mdl["model"].dev(Z) / mdl["ref"]
        flag = s > mdl["threshold"]
        ev_id = np.zeros(len(df), dtype=int)
        k = 0
        for g in pd.unique(groups):
            idx = np.where(groups == g)[0]
            for (i, j) in find_events(flag[idx]):
                k += 1
                rows = idx[i:j + 1]
                ev_id[rows] = k
                share = ratio[rows].mean(0)
                share = share / share.sum()
                comp = {c: float(sum(v for v, f in zip(share, feat) if f.split("_")[0] == c))
                        for c in sorted({f.split("_")[0] for f in feat})}
                top = np.argsort(-share)[: a.top]
                ts = df["timestamp"].values[rows] if "timestamp" in df.columns else np.arange(len(rows))
                step = float(np.median(np.diff(df["timestamp"].values[idx]))) if "timestamp" in df.columns and len(idx) > 1 else 1.0
                events.append(dict(
                    modelo=n, grupo=g, evento=k,
                    inicio=datetime.fromtimestamp(ts[0]).strftime("%H:%M:%S") if "timestamp" in df.columns else int(rows[0]),
                    inicio_ts=ts[0], fin_ts=ts[-1], filas=len(rows), duracion_s=round(len(rows) * step, 1),
                    puntuacion_sobre_umbral=float(s[rows].mean() / mdl["threshold"]),
                    componente=max(comp, key=comp.get), peso_componente=round(max(comp.values()), 3),
                    variables=" | ".join(f"{feat[t]} ({100 * share[t]:.0f}%)" for t in top)))
        out[f"score_{n}"] = s
        out[f"umbral_{n}"] = mdl["threshold"]
        out[f"marca_{n}"] = flag.astype(int)
        out[f"evento_{n}"] = ev_id

    base = a.out or os.path.splitext(a.csv)[0]
    out.to_csv(base + "_detect.csv", index=False)
    ev_df = pd.DataFrame(events)
    ev_df.to_csv(base + "_events.csv", index=False)
    print(f"{len(df)} filas puntuadas ({'todos los runs' if grp_col else 'un solo grupo'})")
    for n in names:
        e = ev_df[ev_df.modelo == n] if len(ev_df) else ev_df
        print(f"\n== {n}: {len(e)} evento(s), {int(out[f'marca_{n}'].sum())} filas marcadas")
        for _, r in e.head(25).iterrows():
            print(f"  [{r.grupo}] {r.inicio}  {r.duracion_s:>5.0f}s  x{r.puntuacion_sobre_umbral:.1f} umbral  "
                  f"-> {r.componente} ({100 * r.peso_componente:.0f}%): {r.variables}")
        if len(e) > 25:
            print(f"  ... y {len(e) - 25} mas (ver {base}_events.csv)")
    print(f"\nGuardado: {base}_detect.csv y {base}_events.csv")


if __name__ == "__main__":
    main()
