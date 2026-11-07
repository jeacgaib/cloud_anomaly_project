#!/usr/bin/env python3
"""Generates report charts in informe/graficos/ from results/ and the final dataset.
Usage (from project root):  python informe/generar_graficos.py data/campaign_<date>.csv
"""
import os
import sys

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = os.path.join("informe", "graficos")
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"
FAULT, WARN = "#f3d9b0", "#b5441b"
IF_C, AE_C = "#eb6834", "#2a78d6"   # Isolation Forest and Autoencoder colors
MODELS = [("Isolation Forest", IF_C), ("Autoencoder", AE_C)]
COMP = {"pedidos": "#2a78d6", "pagos": "#eb6834", "notificaciones": "#1baf7a", "usuarios": "#eda100",
        "postgres": "#e87ba4", "nginx": "#6250d6"}

# English component translations for plots
COMP_LABELS = {"pedidos": "Orders", "pagos": "Payments", "notificaciones": "Notifications", 
               "usuarios": "Users", "postgres": "PostgreSQL", "nginx": "Nginx"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "font.size": 10,
    "text.color": INK, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.axisbelow": True, "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "legend.frameon": False, "xtick.major.size": 0, "ytick.major.size": 0})


def groups(df):
    g = [(s, v) for s in ("cpu", "latency") for v in sorted(df[df.escenario == s].severidad.astype(float).unique())]
    return g, [f"CPU {v:g}" if s == "cpu" else f"Lat. {v:g} ms" for s, v in g]


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=200, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def arquitectura():
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    ax.set_xlim(0, 105)
    ax.set_ylim(0, 63)
    ax.axis("off")

    def box(x, y, w, h, title, sub="", fc="#eef4fb", ec=AE_C):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.2,rounding_size=1.2", fc=fc, ec=ec, lw=1.2))
        ax.text(x + w / 2, y + h / 2 + (1.4 if sub else 0), title, ha="center", va="center", fontsize=9.5, fontweight="bold")
        if sub:
            ax.text(x + w / 2, y + h / 2 - 1.7, sub, ha="center", va="center", fontsize=7.6, color=MUTED)

    def arrow(a, b, ls="-"):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, lw=1.2, color=MUTED, linestyle=ls,
                                     shrinkA=0, shrinkB=0))

    grey = dict(fc="#f2f1ec", ec=MUTED)
    box(1, 36, 14, 9, "JMeter", "50 rps · 200 threads", **grey)
    box(20, 36, 13, 9, "Nginx", "gateway :8000")
    box(39, 43, 16, 9, "Orders", "POST /pedido · 80 %")
    box(39, 26, 16, 9, "Users", "GET /usuarios · 20 %")
    box(63, 48, 17, 8, "Payments", "POST /procesar")
    box(63, 36, 17, 8, "Notifications", "POST /notificar")
    box(87, 33, 16, 10, "PostgreSQL", "4 tables", fc="#f7f0f4", ec="#c2527f")
    
    arrow((15.4, 40.5), (19.6, 40.5))
    arrow((33.4, 41.5), (38.6, 46))
    arrow((33.4, 39.5), (38.6, 32))
    arrow((55.4, 49), (62.6, 52))
    arrow((55.4, 46), (62.6, 41))
    arrow((80.4, 52), (93, 43.5))
    arrow((80.4, 40), (86.6, 39))
    ax.plot([55.4, 60.5], [44.5, 34.4], color=MUTED, lw=1.2)
    arrow((60.5, 34.4), (86.6, 35.6))
    arrow((55.4, 29), (86.6, 34))
    
    # Injected faults
    ax.text(47, 54.2, "Fault 1: CPU overload", ha="center", fontsize=8.5, color=WARN, fontweight="bold")
    ax.annotate("Fault 2: Network latency\n(netem, Orders→Payments only)", xy=(59, 50.6), xytext=(57.5, 60), fontsize=8.2,
                color=WARN, fontweight="bold", ha="left", va="center", annotation_clip=False,
                arrowprops=dict(arrowstyle="-", color=WARN, lw=0.9))
    
    # Monitoring and analysis
    ax.add_patch(FancyBboxPatch((1, 2), 102, 17, boxstyle="round,pad=0.2,rounding_size=1.2", fc="#f7f7f4", ec=GRID, lw=1.2))
    ax.text(3, 17, "Monitoring & Analysis", fontsize=9, color=MUTED, fontweight="bold")
    box(4, 4.5, 18, 8.5, "docker_exporter", "CPU, RAM, throttling", **grey)
    box(25, 4.5, 18, 8.5, "nginx_exporter", "rps, connections", **grey)
    box(46, 4.5, 15, 8.5, "Prometheus", "every 5 s", **grey)
    box(65, 4.5, 15, 8.5, "CSV Dataset", "export_dataset.py", **grey)
    box(84, 4.5, 17, 8.5, "IF / Autoencoder", "detection + XAI")
    
    arrow((43.4, 8.7), (45.6, 8.7))
    arrow((61.4, 8.7), (64.6, 8.7))
    arrow((80.4, 8.7), (83.6, 8.7))
    arrow((53.5, 24.8), (53.5, 13.4), ls="--")
    
    ax.text(54.5, 22.2, "/metrics from each service", fontsize=7.8, color=MUTED, va="center")
    ax.add_patch(FancyArrowPatch((13, 13.4), (49, 13.4), connectionstyle="arc3,rad=-0.07", arrowstyle="-|>", mutation_scale=11,
                                 lw=1.2, color=MUTED, shrinkA=0, shrinkB=0))
    save(fig, "01_arquitectura.png")


def efecto(d):
    picks = [("Normal operation (50 rps)", "normal", 0.0, "pedidos_latency_ms", "Orders Latency (ms)", 50),
             ("CPU overload (duty 0.6)", "cpu", 0.6, "pedidos_cpu_cores", "Orders CPU (cores)", None),
             ("Network latency (+300 ms)", "latency", 300.0, "pedidos_latency_ms", "Orders Latency (ms)", None)]
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.3))
    for ax, (title, sc, sev, col, yl, rps) in zip(axes, picks):
        q = d[(d.scenario == sc) & (d.severity == sev)]
        if rps:
            q = q[q.rps_target == rps]
        r = q[q.run_id == sorted(q.run_id.unique())[0]].sort_values("timestamp")
        t = r.timestamp - r.timestamp.min()
        if r.label.sum():
            ax.axvspan(t[r.label == 1].min(), t[r.label == 1].max(), color=FAULT, alpha=0.55, lw=0, label="Active fault")
            ax.legend(loc="upper left", fontsize=8)
        ax.plot(t, r[col], color=AE_C, lw=1.6)
        ax.set_title(title)
        ax.set_xlabel("Time since run start (s)")
        ax.set_ylabel(yl)
        ax.set_ylim(bottom=0)
    fig.tight_layout()
    save(fig, "02_efecto_fallas_por_escenario.png")


def puntuacion(res):
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 6))
    for i, (sc, sev, lab) in enumerate([("cpu", 0.6, "CPU 0.6"), ("latency", 300.0, "Latency 300 ms")]):
        run = sorted(res[(res.scenario == sc) & (res.severity == sev)].run_id.unique())[0]
        r = res[res.run_id == run].sort_values("timestamp")
        t = np.arange(len(r)) * 5
        for j, (n, c) in enumerate(MODELS):
            ax = axes[i, j]
            ax.fill_between(t, 0, 1, where=r.label.values == 1, transform=ax.get_xaxis_transform(), color=FAULT,
                            alpha=0.55, lw=0, label="Active fault")
            ax.plot(t, r[f"s_{n}"], color=c, lw=1.5, label="Score")
            ax.axhline(r[f"thr_{n}"].iloc[0], color=INK, ls="--", lw=1, label="Threshold (p95)")
            if n == "Autoencoder":
                ax.set_yscale("log")
            ax.set_ylabel("Score (log)" if n == "Autoencoder" else "Score")
            ax.set_title(f"{n}: {lab}")
            if i == 1:
                ax.set_xlabel("Time without warmup or recovery (s)")
    h, l = axes[0, 0].get_legend_handles_labels()
    keep = [i for i, t in enumerate(l) if t != "Score"]
    fig.legend([h[i] for i in keep], [l[i] for i in keep], loc="upper center", ncol=2, fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save(fig, "03_puntuacion_vs_umbral.png")


def barras(ax, g, labels, values):
    w, x = 0.38, np.arange(len(g))
    for k, (n, c) in enumerate(MODELS):
        ax.bar(x + (k - 0.5) * w, values[n], w - 0.04, color=c, label=n)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")


def comparacion(row, ev):
    g, labels = groups(row[row.escenario != "TODAS"])
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.9))

    def get(n, s, v, col):
        return row[(row.modelo == n) & (row.escenario == s) & (row.severidad == v)][col].iloc[0]

    barras(axes[0], g, labels, {n: [get(n, s, v, "f1") for s, v in g] for n, _ in MODELS})
    axes[0].set_title("Row-level F1-Score")
    axes[0].set_ylim(0, 1.05)
    
    det = {n: [ev[(ev.modelo == n) & (ev.escenario == s) & (ev.severidad == v)].detectada.sum() for s, v in g] for n, _ in MODELS}
    barras(axes[1], g, labels, det)
    axes[1].set_title("Detected faults (out of 3 runs)")
    axes[1].set_yticks(range(4))
    axes[1].set_ylim(0, 3.2)
    
    barras(axes[2], g, labels, {n: [get(n, s, v, "auc") for s, v in g] for n, _ in MODELS})
    axes[2].set_title("ROC AUC (threshold-independent)")
    axes[2].set_ylim(0, 1.05)
    
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=2, fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    save(fig, "04_comparacion_f1_deteccion_auc.png")


def tiempos(row, ev):
    g, labels = groups(row[row.escenario != "TODAS"])
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    for k, (n, c) in enumerate(MODELS):
        first = True
        for i, (s, v) in enumerate(g):
            y = ev[(ev.modelo == n) & (ev.escenario == s) & (ev.severidad == v) & ev.detectada].t_deteccion_s.values
            if not len(y):
                continue
            off = np.linspace(-0.06, 0.06, len(y)) if len(y) > 1 else np.zeros(1)
            ax.scatter(i + (k - 0.5) * 0.32 + off, y, s=52, color=c, edgecolor=SURFACE, lw=1, zorder=3, label=n if first else None)
            first = False
    ax.set_xticks(range(len(g)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("Detection time (s)")
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper center", fontsize=9, ncol=2)
    fig.tight_layout()
    save(fig, "05_tiempo_de_deteccion.png")


def normales(res, d):
    rp = d.groupby("run_id").rps_target.first()
    r = res[res.scenario == "normal"].copy()
    r["rps"] = r.run_id.map(rp)
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    loads = sorted(r.rps.unique())
    x, w = np.arange(len(loads)), 0.38
    for k, (n, c) in enumerate(MODELS):
        v = [100 * r[r.rps == q][f"flag_{n}"].mean() for q in loads]
        b = ax.bar(x + (k - 0.5) * w, v, w - 0.04, color=c, label=n)
        ax.bar_label(b, fmt="%.1f %%", fontsize=8.5, padding=2, color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{q:g} rps" for q in loads])
    ax.set_ylabel("Rows flagged as anomalous (%)")
    ax.set_ylim(0, 118)
    ax.legend(fontsize=9, loc="upper right")
    fig.tight_layout()
    save(fig, "06_falsas_alarmas_runs_normales.png")


def explicacion(row, ex):
    g, labels = groups(row[row.escenario != "TODAS"])
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
    x = np.arange(len(g))
    for ax, (n, _) in zip(axes, MODELS):
        bottom = np.zeros(len(g))
        counts = []
        for c, col in COMP.items():
            vals, counts = [], []
            for s, v in g:
                q = ex[(ex.modelo == n) & (ex.escenario == s) & (ex.severidad == v)]
                vals.append(q[f"share_{c}"].mean() if len(q) else 0.0)
                counts.append(len(q))
            ax.bar(x, vals, 0.68, bottom=bottom, color=col, edgecolor=SURFACE, lw=1, label=COMP_LABELS[c])
            bottom += np.array(vals)
        for i, k in enumerate(counts):
            ax.text(i, 1.03 if k else 0.03, f"n={k}", ha="center", fontsize=8.2, color=MUTED)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right")
        ax.set_title(n)
        ax.set_ylim(0, 1.12)
    axes[0].set_ylabel("Contribution share")
    h, l = axes[1].get_legend_handles_labels()
    fig.legend(h, l, loc="center right", fontsize=9)
    fig.tight_layout(rect=(0, 0, 0.88, 1))
    save(fig, "07_explicacion_por_componente.png")


def main():
    os.makedirs(OUT, exist_ok=True)
    d = pd.read_csv(sys.argv[1])
    res = pd.read_csv("results/scores_por_fila.csv")
    row = pd.read_csv("results/metricas_por_fila.csv")
    ev = pd.read_csv("results/deteccion_por_evento.csv")
    ex = pd.read_csv("results/explicaciones_por_run.csv")
    row["severidad"] = pd.to_numeric(row.severidad, errors="coerce")
    arquitectura()
    efecto(d)
    puntuacion(res)
    comparacion(row, ev)
    tiempos(row, ev)
    normales(res, d)
    explicacion(row, ex)
    print("Graficos en", OUT)


if __name__ == "__main__":
    main()