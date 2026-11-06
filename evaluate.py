#!/usr/bin/env python3
"""Evaluacion P1: Isolation Forest (baseline) vs Autoencoder, con explicacion inicial.

Uso:  python evaluate.py data/campaign_<fecha>.csv [--out results]

Protocolo
  * Validacion cruzada AGRUPADA POR RUN (K=3): los runs de cada (escenario, severidad) se reparten entre
    los folds; el modelo se entrena solo con filas normales (label=0) de los OTROS folds y se evalua en
    todas las filas (baseline, fault, post) de los runs del fold. Se excluyen warmup, recovery y runs con
    run_ok=False. Precision/Recall/F1 globales incluyen los runs normales (falsos positivos).
  * Umbral = percentil 95 de las puntuaciones fuera de muestra sobre datos normales de entrenamiento
    (calibrado sin mirar los datos de test). Alerta = 2 filas consecutivas por encima del umbral.
  * Features: todas las numericas salvo RAM absoluta (deriva entre runs), nginx_conn_active (= hilos de
    JMeter) y columnas constantes.
Explicacion (XAI inicial)
  * Autoencoder: error de reconstruccion por variable; Isolation Forest: |z| por variable (sustituto, IF no
    trae atribucion propia). Ambos se normalizan con el valor tipico en datos normales fuera de muestra.
  * Se agrega por componente (nginx, pedidos, usuarios, pagos, notificaciones, postgres) para señalar el
    servicio afectado. Solo se explican las filas de falla que el modelo marco (fallas no detectadas: sin explicacion).
  * Isolation Forest no trae atribucion propia: |z| es la desviacion estandarizada, comun a cualquier modelo.
"""
import argparse
import os
import warnings

import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from anomaly_models import COMPONENTS, MODELS, PCT, Scaler, feature_columns  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

warnings.filterwarnings("ignore")
K, STEP = 3, 5.0
EXPECTED_VARS = {
    "cpu": {"pedidos_cpu_cores", "pedidos_cpu_throttled_ps"},
    "latency": {"pedidos_latency_ms", "pedidos_latency_p95_ms"},
}


# ------------------------------------------------------------------ datos
def load(path, sin_throttled=False):
    d = pd.read_csv(path)
    d = d[d.phase.isin(["baseline", "fault", "post"]) & d.run_ok.ne(False)].copy()   # runs con baseline inestable fuera
    feat = feature_columns(d)
    if sin_throttled:   # analisis exploratorio: ver seccion de sensibilidad del informe
        feat = [c for c in feat if not c.endswith("cpu_throttled_ps")]
    d[feat] = d[feat].fillna(0)
    d = d.sort_values(["run_id", "timestamp"]).reset_index(drop=True)
    d["fold"] = -1
    for _, g in d.groupby(["scenario", "severity"]):
        for i, r in enumerate(sorted(g.run_id.unique())):
            d.loc[d.run_id == r, "fold"] = i % K
    return d, feat


# ------------------------------------------------------------------ evaluacion por fold
def run_cv(d, feat):
    rows, devs = [], {m.name: [] for m in MODELS}
    refs = {m.name: {} for m in MODELS}
    for f in range(K):
        tr = d[(d.fold != f) & (d.label == 0)]
        te = d[d.fold == f]
        sc = Scaler().fit(tr[feat].values)
        Ztr, Zte = sc.transform(tr[feat].values), sc.transform(te[feat].values)
        runs = sorted(tr.run_id.unique())
        grp = tr.run_id.map({r: i % 2 for i, r in enumerate(runs)}).values
        keep = ["run_id", "scenario", "severity", "timestamp", "phase", "label"] + (["fault_start"] if "fault_start" in te else [])
        part = te[keep].copy()
        for M in MODELS:
            oof_s, oof_d = np.zeros(len(tr)), np.zeros((len(tr), len(feat)))
            for g in (0, 1):
                m = M().fit(Ztr[grp != g])
                oof_s[grp == g], oof_d[grp == g] = m.score(Ztr[grp == g]), m.dev(Ztr[grp == g])
            thr = np.quantile(oof_s, PCT)
            refs[M.name][f] = np.maximum(oof_d.mean(0), 1e-9)
            final = M().fit(Ztr)
            part[f"s_{M.name}"] = final.score(Zte)
            part[f"thr_{M.name}"] = thr
            part[f"flag_{M.name}"] = (part[f"s_{M.name}"] > thr).astype(int)
            devs[M.name].append(final.dev(Zte))
        part["fold"] = f
        rows.append(part)
        print(f"  fold {f + 1}/{K} listo", flush=True)
    res = pd.concat(rows, ignore_index=True)
    return res, {k: np.vstack(v) for k, v in devs.items()}, refs


# ------------------------------------------------------------------ metricas
def alerts(flag, ts):
    out, run = [], 0
    for fl, t in zip(flag, ts):
        run = run + 1 if fl else 0
        if run == 2:
            out.append(t)
    return out


def prf(y, p):
    tp, fp, fn = int(((p == 1) & (y == 1)).sum()), int(((p == 1) & (y == 0)).sum()), int(((p == 0) & (y == 1)).sum())
    P, R = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return P, R, (2 * P * R / (P + R) if P + R else 0.0)


def metrics(res):
    row_rows, ev_rows, fa_rows = [], [], []
    faults = res[res.scenario != "normal"]
    for M in MODELS:
        n = M.name
        for (sc, sev), g in faults.groupby(["scenario", "severity"]):
            P, R, F = prf(g.label.values, g[f"flag_{n}"].values)
            aucs, aps = [], []
            for _, r in g.groupby("run_id"):
                aucs.append(roc_auc_score(r.label, r[f"s_{n}"]))
                aps.append(average_precision_score(r.label, r[f"s_{n}"]))
            row_rows.append(dict(modelo=n, escenario=sc, severidad=sev, precision=P, recall=R, f1=F,
                                 auc=np.mean(aucs), pr_auc=np.mean(aps), filas_falla=int(g.label.sum())))
            for run, r in g.groupby("run_id"):
                r = r.sort_values("timestamp")
                al = alerts(r[f"flag_{n}"].values, r.timestamp.values)
                ft = r.timestamp[r.label == 1]
                fe = ft.max()
                # inicio exacto si el CSV lo trae; si no (CSV antiguo), se estima como primera fila de falla - STEP
                fs_est = r.fault_start.iloc[0] if "fault_start" in r and pd.notna(r.fault_start.iloc[0]) else ft.min() - STEP
                hit = [a for a in al if fs_est < a <= fe]
                ev_rows.append(dict(modelo=n, escenario=sc, severidad=sev, run_id=run, detectada=bool(hit),
                                    t_deteccion_s=(min(hit) - fs_est) if hit else np.nan))
        # global: TODOS los runs, incluidos los normales (sus filas marcadas cuentan como falsos positivos)
        P, R, F = prf(res.label.values, res[f"flag_{n}"].values)
        row_rows.append(dict(modelo=n, escenario="TODAS", severidad="", precision=P, recall=R, f1=F,
                             auc=np.nan, pr_auc=np.nan, filas_falla=int(res.label.sum())))
        # falsas alarmas: alertas en filas normales, por hora de operacion normal
        n_alerts, n_rows = 0, 0
        for run, r in res.groupby("run_id"):
            r = r.sort_values("timestamp")
            al = alerts(r[f"flag_{n}"].values, r.timestamp.values)
            lab = dict(zip(r.timestamp, r.label))
            n_alerts += sum(1 for a in al if lab[a] == 0)
            n_rows += int((r.label == 0).sum())
        nr = res[(res.scenario == "normal")]
        fpr_norm = nr[f"flag_{n}"].mean()
        fa_rows.append(dict(modelo=n, falsas_alarmas_por_hora=n_alerts / (n_rows * STEP / 3600),
                            filas_normales_marcadas_pct_runs_normales=100 * fpr_norm))
    return pd.DataFrame(row_rows), pd.DataFrame(ev_rows), pd.DataFrame(fa_rows)


def sensitivity(res):
    """Barrido del umbral (multiplicador sobre el umbral calibrado). Los resultados usan etiquetas de test:
    es una cota superior optimista, no un resultado operativo."""
    rows = []
    for M in MODELS:
        n = M.name
        ratio = (res[f"s_{n}"] / res[f"thr_{n}"]).values
        y = res.label.values
        isf = (res.scenario != "normal").values
        for m in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.25, 1.5]:
            p = (ratio > m).astype(int)
            P, R, F = prf(y, p)   # todos los runs, incluidos los normales
            rows.append(dict(modelo=n, multiplicador_umbral=m, precision=P, recall=R, f1=F,
                             marcadas_pct_en_runs_normales=100 * p[~isf].mean()))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ explicacion
def explain(res, devs, refs, feat):
    out = []
    comp_of = [c.split("_")[0] for c in feat]
    for M in MODELS:
        n = M.name
        for run, r in res[res.scenario != "normal"].groupby("run_id"):
            r = r.sort_values("timestamp")
            sel = r[(r.label == 1) & (r[f"flag_{n}"] == 1)]   # solo filas de falla que el modelo marco
            if sel.empty:
                continue   # falla no detectada: no hay nada que explicar
            f = int(r.fold.iloc[0])
            contrib = devs[n][sel.index.values].mean(0) / refs[n][f]
            share = contrib / contrib.sum()
            comp_share = {c: float(sum(s for s, cc in zip(share, comp_of) if cc == c)) for c in COMPONENTS}
            top = np.argsort(-share)[:3]
            scn = r.scenario.iloc[0]
            top_vars = [feat[i] for i in top]
            out.append(dict(modelo=n, escenario=scn, severidad=r.severity.iloc[0], run_id=run,
                            componente_top=max(comp_share, key=comp_share.get),
                            top1=top_vars[0], top2=top_vars[1], top3=top_vars[2],
                            share_top1=float(share[top[0]]), share_top2=float(share[top[1]]),
                            share_top3_var=float(share[top[2]]), share_top3=float(share[top].sum()),
                            servicio_ok=max(comp_share, key=comp_share.get) == "pedidos",
                            variable_ok_top3=bool(set(top_vars) & EXPECTED_VARS[scn]),
                            variable_ok_top1=top_vars[0] in EXPECTED_VARS[scn],
                            **{f"share_{c}": v for c, v in comp_share.items()}))
    return pd.DataFrame(out)


# ------------------------------------------------------------------ graficas
def figures(res, row_df, ev_df, ex_df, out):
    names = [m.name for m in MODELS]
    # 1) lineas de tiempo de dos runs representativos
    picks = [("cpu", 0.6), ("latency", 300.0)]
    fig, axes = plt.subplots(2, 2, figsize=(12, 6.5), sharex="row")
    for i, (sc, sev) in enumerate(picks):
        run = sorted(res[(res.scenario == sc) & (res.severity == sev)].run_id.unique())[0]
        r = res[res.run_id == run].sort_values("timestamp")
        t = (r.timestamp - r.timestamp.min()).values
        for j, n in enumerate(names):
            ax = axes[i, j]
            ax.plot(t, r[f"s_{n}"], lw=1, color="#2a6fb0")
            ax.axhline(r[f"thr_{n}"].iloc[0], color="#c0392b", ls="--", lw=1, label="umbral (p95)")
            fault = r.label.values == 1
            ax.fill_between(t, 0, 1, where=fault, transform=ax.get_xaxis_transform(), color="#f5b041", alpha=0.25,
                            label="falla inyectada")
            fl = r[f"flag_{n}"].values == 1
            ax.scatter(t[fl], r[f"s_{n}"].values[fl], s=14, color="#c0392b", zorder=3, label="alerta (fila)")
            ax.set_yscale("log")
            unit = "duty" if sc == "cpu" else "ms"
            ax.set_title(f"{n} – {sc} {sev:g} {unit}", fontsize=10)
            if j == 0:
                ax.set_ylabel("puntuacion de anomalia (log)")
            if i == 1:
                ax.set_xlabel("tiempo desde el fin del warmup (s)")
    axes[0, 0].legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_lineas_de_tiempo.png"), dpi=130)
    plt.close(fig)

    # 2) F1 y tasa de deteccion por severidad
    groups = [(sc, sev) for sc in ("cpu", "latency") for sev in sorted(row_df[row_df.escenario == sc].severidad.unique())]
    labels = [f"CPU {s:g}" if sc == "cpu" else f"Lat {s:g} ms" for sc, s in groups]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    w, x = 0.38, np.arange(len(groups))
    for k, n in enumerate(names):
        f1 = [row_df[(row_df.modelo == n) & (row_df.escenario == sc) & (row_df.severidad == sev)].f1.iloc[0] for sc, sev in groups]
        dr = [ev_df[(ev_df.modelo == n) & (ev_df.escenario == sc) & (ev_df.severidad == sev)].detectada.mean() for sc, sev in groups]
        axes[0].bar(x + (k - 0.5) * w, f1, w, label=n)
        axes[1].bar(x + (k - 0.5) * w, dr, w, label=n)
    for ax, ttl in zip(axes, ["F1 por fila", "Fallas detectadas (fraccion de runs)"]):
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=35, ha="right")
        ax.set_ylim(0, 1.05)
        ax.set_title(ttl)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(os.path.join(out, "fig_comparacion.png"), dpi=130)
    plt.close(fig)

    # 3) explicacion: reparto por componente
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
    colors = dict(zip(COMPONENTS, ["#95a5a6", "#c0392b", "#2980b9", "#27ae60", "#e67e22", "#8e44ad"]))
    for ax, n in zip(axes, names):
        bottom = np.zeros(len(groups))
        for c in COMPONENTS:
            vals = np.nan_to_num([ex_df[(ex_df.modelo == n) & (ex_df.escenario == sc) & (ex_df.severidad == sev)][f"share_{c}"].mean()
                                  for sc, sev in groups])   # 0 si no hubo ninguna deteccion en ese grupo
            ax.bar(x, vals, bottom=bottom, label=c, color=colors[c])
            bottom += vals
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=35, ha="right")
        ax.set_title(f"{n}: componente señalado (fallas detectadas)")
    axes[0].set_ylabel("proporcion de la contribucion")
    axes[1].legend(fontsize=8, bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_explicacion_componentes.png"), dpi=130)
    plt.close(fig)


# ------------------------------------------------------------------ informe
def md(df, floatfmt=3):
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        cells = [f"{v:.{floatfmt}f}" if isinstance(v, (float, np.floating)) and not np.isnan(v)
                 else ("" if isinstance(v, float) and np.isnan(v) else str(v)) for v in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_summary(out, feat, d, row_df, ev_df, fa_df, ex_df, sens_df):
    L = ["# Resultados P1: Isolation Forest vs Autoencoder", "",
         f"- Runs: {d.run_id.nunique()} ({', '.join(f'{k}: {v}' for k, v in d.groupby('scenario').run_id.nunique().items())}); "
         f"validacion cruzada agrupada por run (K={K}).",
         f"- Features ({len(feat)}): {', '.join(feat)}",
         "- Umbral: percentil 95 fuera de muestra sobre normales de entrenamiento. Alerta = 2 filas consecutivas.",
         f"- Resolucion temporal: {STEP:.0f} s (las tasas usan ventanas de 15 s).", ""]
    r = row_df.copy()
    L += ["## Metricas por fila",
          "Por severidad: filas de los runs de esa falla. TODAS: todos los runs, incluidos los normales.", md(r), ""]
    e = (ev_df.groupby(["modelo", "escenario", "severidad"])
         .agg(runs=("run_id", "size"), detectadas=("detectada", "sum"), t_deteccion_mediana_s=("t_deteccion_s", "median"))
         .reset_index())
    L += ["## Deteccion por evento (run)", md(e, 1), ""]
    L += ["## Falsas alarmas", md(fa_df, 2), ""]
    best = sens_df.loc[sens_df.groupby("modelo").f1.idxmax()]
    L += ["## Sensibilidad del umbral (cota superior, usa etiquetas de test)",
          "Mejor multiplicador del umbral calibrado por modelo y su rendimiento:", md(best, 3), ""]
    x = (ex_df.groupby(["modelo", "escenario", "severidad"])
         .agg(runs_explicados=("run_id", "size"), servicio_ok=("servicio_ok", "mean"), variable_ok_top1=("variable_ok_top1", "mean"),
              variable_ok_top3=("variable_ok_top3", "mean"), share_var1=("share_top1", "mean"),
              share_var2=("share_top2", "mean"), share_var3=("share_top3_var", "mean")).reset_index())
    L += ["## Explicacion (fraccion de runs detectados; solo filas de falla marcadas por el modelo)", md(x, 2), ""]
    modes = (ex_df.groupby(["modelo", "escenario", "severidad"])
             .agg(top1_mas_frecuente=("top1", lambda s: s.mode().iloc[0]),
                  top2=("top2", lambda s: s.mode().iloc[0]), top3=("top3", lambda s: s.mode().iloc[0])).reset_index())
    L += ["## Variables mas señaladas", md(modes), ""]
    open(os.path.join(out, "summary.md"), "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default="results")
    ap.add_argument("--sin-throttled", action="store_true", help="excluye *_cpu_throttled_ps (analisis exploratorio)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    d, feat = load(a.csv, a.sin_throttled)
    print(f"{d.run_id.nunique()} runs, {len(d)} filas, {len(feat)} features")
    res, devs, refs = run_cv(d, feat)
    row_df, ev_df, fa_df = metrics(res)
    ex_df = explain(res, devs, refs, feat)
    sens_df = sensitivity(res)
    sens_df.to_csv(os.path.join(a.out, "sensibilidad_umbral.csv"), index=False)
    res.to_csv(os.path.join(a.out, "scores_por_fila.csv"), index=False)
    row_df.to_csv(os.path.join(a.out, "metricas_por_fila.csv"), index=False)
    ev_df.to_csv(os.path.join(a.out, "deteccion_por_evento.csv"), index=False)
    fa_df.to_csv(os.path.join(a.out, "falsas_alarmas.csv"), index=False)
    ex_df.to_csv(os.path.join(a.out, "explicaciones_por_run.csv"), index=False)
    figures(res, row_df, ev_df, ex_df, a.out)
    write_summary(a.out, feat, d, row_df, ev_df, fa_df, ex_df, sens_df)
    print(f"Listo -> {a.out}/summary.md")


if __name__ == "__main__":
    main()
