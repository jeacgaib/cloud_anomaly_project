#!/usr/bin/env python3
"""Exporta las metricas de Prometheus a CSV etiquetado para un run.

Uso: python export_dataset.py data/<run_id>_events.json [--warmup 60] [--recovery-lag 90]

Columnas por componente (nginx_*, pedidos_*, usuarios_*, pagos_*, notificaciones_*, postgres_*):
  cpu_cores, ram_mb, cpu_throttled_ps (periodos CFS limitados/s),
  y segun el caso: latency_ms, latency_p95_ms, rps, errors_ps, conn_active.
  - latency_* queda vacia (NaN) cuando en la ventana no termino ninguna peticion.
Etiquetas:
  label  1 = falla inyectada activa, 0 = resto
  phase  warmup | baseline | fault | recovery | post
         (excluir warmup y recovery al entrenar y evaluar)
  run_id, rps_target, severity (cpu_duty o latency_ms): para agrupar y separar train/test POR RUN
"""
import argparse
import json
import os

import pandas as pd
import requests

PROM = os.getenv("PROM_URL", "http://localhost:9090")
STEP = 5
W = "15s"

# prefijo de columnas -> (nombre de contenedor/servicio, familias de metricas)
SERVICES = {
    "nginx": ("nginx", ["container", "nginx"]),
    "pedidos": ("servicio_pedidos", ["container", "app"]),
    "usuarios": ("servicio_usuarios", ["container", "app"]),
    "pagos": ("servicio_pagos", ["container", "app"]),
    "notificaciones": ("servicio_notificaciones", ["container", "app"]),
    "postgres": ("postgres", ["container"]),
}
GAUGES = ("cpu_cores", "ram_mb", "conn_active")  # se rellenan hacia delante


def queries(prefix, svc, kinds):
    p = prefix
    out = {}
    if "container" in kinds:
        cpu = [f'dockerstats_cpu_cores{{container="{svc}"}}']
        ram = [f'dockerstats_memory_mb{{container="{svc}"}}']
        if "app" in kinds:  # respaldo con metricas del proceso
            cpu.append(f'rate(process_cpu_seconds_total{{job="{svc}"}}[{W}])')
            ram.append(f'process_resident_memory_bytes{{job="{svc}"}}/1e6')
        out["cpu_cores"], out["ram_mb"] = cpu, ram
        out["cpu_throttled_ps"] = [f'rate(dockerstats_cpu_throttled_periods_total{{container="{svc}"}}[{W}])']
    if "app" in kinds:
        out["latency_ms"] = [
            f"1000*rate({p}_request_latency_seconds_sum[{W}])/rate({p}_request_latency_seconds_count[{W}])"
        ]
        out["latency_p95_ms"] = [
            f"1000*histogram_quantile(0.95, sum by (le)(rate({p}_request_latency_seconds_bucket[{W}])))"
        ]
        out["rps"] = [f"sum(rate({p}_requests_total[{W}]))"]
        out["errors_ps"] = [f"rate({p}_errors_total[{W}])"]
    if "nginx" in kinds:
        out["rps"] = [f"rate(nginx_http_requests_total[{W}])"]
        out["conn_active"] = ["nginx_connections_active"]
    return out


def qrange(q, start, end):
    r = requests.get(
        f"{PROM}/api/v1/query_range",
        params={"query": q, "start": start, "end": end, "step": STEP},
        timeout=30,
    )
    r.raise_for_status()
    res = r.json()["data"]["result"]
    if not res:
        return None
    return pd.Series({float(t): float(v) for t, v in res[0]["values"]})


def add_phase(df, ev, warmup, recovery_lag, min_recovery=20):
    ts = df.index.to_series()
    t0, fs, fe = ev["t_start"], ev.get("fault_start"), ev.get("fault_end")
    phase = pd.Series("baseline", index=df.index)
    phase[ts < t0 + warmup] = "warmup"
    if fs and fe:
        # las tasas usan ventanas de 15 s: el efecto de la falla se arrastra ~15 s tras fault_end
        rec_end = max(ev.get("recovered_at") or (fe + recovery_lag), fe + min_recovery)
        if not ev.get("recovered_at"):
            print(f"[aviso] el run no registra recuperacion; fase recovery = {recovery_lag}s tras la falla")
        phase[(ts > fe) & (ts <= rec_end)] = "recovery"
        phase[ts > rec_end] = "post"
        phase[(ts >= fs) & (ts <= fe)] = "fault"   # la falla tiene prioridad sobre warmup
        if t0 + warmup >= fs:
            print("[aviso] el warmup llega hasta la falla; reduce --warmup o aumenta --baseline")
    return phase


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--out")
    ap.add_argument("--warmup", type=int, default=60, help="s iniciales (arranque de JMeter + rampa)")
    ap.add_argument("--recovery-lag", type=int, default=90, help="s de recovery si no hubo sonda")
    ap.add_argument("--min-recovery", type=int, default=20, help="s minimos de fase recovery (ventana de las tasas)")
    args = ap.parse_args()

    ev = json.load(open(args.events))
    start, end = ev["t_start"], ev["t_end"]
    idx = pd.Index([start + i * STEP for i in range(int((end - start) // STEP) + 1)])
    df = pd.DataFrame(index=idx)

    for prefix, (svc, kinds) in SERVICES.items():
        for metric, options in queries(prefix, svc, kinds).items():
            col = f"{prefix}_{metric}"
            series = None
            for q in options:
                series = qrange(q, start, end)
                if series is not None:
                    break
            if series is None:
                print(f"[aviso] sin datos para {col}")
                df[col] = float("nan")
            else:
                df[col] = series.reindex(idx, method="nearest", tolerance=STEP / 2)

    rate_cols = [c for c in df.columns if c.endswith(("_rps", "_errors_ps", "_throttled_ps"))]
    df[rate_cols] = df[rate_cols].fillna(0)
    gauge_cols = [c for c in df.columns if c.endswith(GAUGES)]
    df[gauge_cols] = df[gauge_cols].ffill()          # latencias NO se rellenan

    fs, fe = ev.get("fault_start"), ev.get("fault_end")
    df["label"] = 0
    if fs and fe:
        df.loc[(df.index >= fs) & (df.index <= fe), "label"] = 1
    df["phase"] = add_phase(df, ev, args.warmup, args.recovery_lag, args.min_recovery)
    p = ev.get("params", {})
    df["run_id"] = ev["run_id"]
    df["rps_target"] = p.get("rps")
    df["severity"] = {"cpu": p.get("cpu_duty"), "latency": p.get("latency_ms")}.get(ev["scenario"], 0)
    df["scenario"] = ev["scenario"]
    df["fault_start"] = fs   # instante exacto de inicio de la falla (vacio en runs normales): tiempo de deteccion
    df["fault_service"] = ev.get("fault_service") or ""
    df.index.name = "timestamp"

    out = args.out or args.events.replace("_events.json", "_dataset.csv")
    df.to_csv(out)
    print(f"{len(df)} filas -> {out}")
    print(df.groupby(["phase", "label"]).size().to_string())


if __name__ == "__main__":
    main()
