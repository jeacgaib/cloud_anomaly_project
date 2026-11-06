#!/usr/bin/env python3
"""Campana de experimentos: ejecuta muchos runs, exporta cada dataset y los une en uno solo.

Para cada run: vacia las tablas -> run_scenario.py -> export_dataset.py -> control de calidad del baseline.
Al final genera data/campaign_<fecha>.csv (todos los runs, con run_id, scenario, severity, rps_target, phase, label)
y data/campaign_<fecha>_manifest.json (que runs salieron bien y cuales sospechosos).

Ejemplos:
  python run_campaign.py --dry-run                 # solo muestra el plan y el tiempo estimado
  python run_campaign.py --repeats 3               # plan completo, 3 repeticiones de cada falla
  python run_campaign.py --only cpu --repeats 2    # solo escenarios de CPU
  python run_campaign.py --resume                  # continua si se interrumpio (omite los ya hechos)
"""
import argparse
import glob
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime

import pandas as pd

# Plan por defecto. "repeats": None -> usa --repeats (los normales se hacen 1 vez por nivel).
PLAN = [
    {"scenario": "normal", "rps": 30, "threads": 150, "repeats": 1},
    {"scenario": "normal", "rps": 50, "threads": 200, "repeats": 1},
    {"scenario": "normal", "rps": 70, "threads": 300, "repeats": 1},
    {"scenario": "cpu", "cpu_duty": 0.2},
    {"scenario": "cpu", "cpu_duty": 0.4},
    {"scenario": "cpu", "cpu_duty": 0.5},
    {"scenario": "cpu", "cpu_duty": 0.6},   # con Notificaciones, 0.8 colapsa Pedidos (ver README)
    {"scenario": "latency", "latency_ms": 100},
    {"scenario": "latency", "latency_ms": 300},
    {"scenario": "latency", "latency_ms": 500},
]
FAULT_DEFAULTS = {"baseline": 180, "fault": 120, "recovery": 120}
MAX_BAD_RUNS = 2   # runs malos seguidos antes de detener la campana


def scenario_args(item, quick, jmeter_bin=None):
    a = ["--scenario", item["scenario"], "--rps", str(item.get("rps", 50)),
         "--threads", str(item.get("threads", 200))]
    if jmeter_bin:
        a += ["--jmeter-bin", jmeter_bin]
    if quick:
        a += ["--rampup", "2"]
    if item["scenario"] == "normal":
        a += ["--duration", "8" if quick else "600"]
    elif quick:
        a += ["--baseline", "3", "--fault-duration", "4", "--recovery", "5"]
    if item["scenario"] == "cpu":
        a += ["--cpu-duty", str(item["cpu_duty"])]
    if item["scenario"] == "latency":
        a += ["--latency-ms", str(item["latency_ms"])]
    return a


def label_of(item):
    sev = item.get("cpu_duty", item.get("latency_ms", ""))
    return f"{item['scenario']}-{sev}-rps{item.get('rps', 50)}".replace("--", "-")


def est_seconds(item, quick):
    if quick:
        return 30
    if item["scenario"] == "normal":
        return 600 + 60
    return sum(FAULT_DEFAULTS.values()) + 60


def baseline_ok(df):
    """Control de calidad: baseline estable (p95 de Pedidos < 200 ms y sin errores)."""
    b = df[df.phase == "baseline"]
    if len(b) < 5:
        return None
    return bool(b.pedidos_latency_p95_ms.mean() < 200 and b.pedidos_errors_ps.mean() < 0.1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", default="", help="lista separada por comas: normal,cpu,latency")
    ap.add_argument("--cooldown", type=int, default=30, help="s de pausa entre runs")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-shuffle", action="store_true", help="no mezclar el orden de los runs")
    ap.add_argument("--warmup", type=int, default=80)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--quick", action="store_true", help="duraciones minimas (solo para probar el flujo)")
    ap.add_argument("--limit", type=int, default=0, help="ejecuta solo los N primeros runs (pruebas)")
    ap.add_argument("--jmeter-bin", default=None, help="ruta a jmeter / jmeter.bat si no esta en el PATH")
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    runs = []
    for item in PLAN:
        if only and item["scenario"] not in only:
            continue
        for rep in range(item.get("repeats") or args.repeats):
            runs.append({**item, "rep": rep + 1})
    if not args.no_shuffle:   # mezclar evita confundir severidad con deriva temporal del equipo
        random.Random(args.seed).shuffle(runs)
    if args.limit:
        runs = runs[: args.limit]

    total_min = sum(est_seconds(r, args.quick) + args.cooldown for r in runs) / 60
    print(f"{len(runs)} runs, tiempo estimado ~{total_min:.0f} min ({total_min / 60:.1f} h)")
    for i, r in enumerate(runs, 1):
        print(f"  {i:2d}. {label_of(r)} (rep {r['rep']})")
    if args.dry_run:
        return

    os.makedirs("data", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = os.path.join("data", "campaign_progress.json")
    entries = {}   # key -> entrada del manifest (un reintento reemplaza a la anterior)
    if args.resume and os.path.exists(manifest_path):
        entries = {m["key"]: m for m in json.load(open(manifest_path))}
    # solo se omiten los runs que salieron bien; los fallidos o con baseline inestable se repiten
    done = {k for k, m in entries.items() if m.get("ok") and m.get("baseline_ok") is not False}

    bad_streak = 0
    for i, r in enumerate(runs, 1):
        key = f"{label_of(r)}#{r['rep']}"
        if key in done:
            print(f"[{i}/{len(runs)}] {key}: ya hecho, se omite")
            continue
        print(f"\n[{i}/{len(runs)}] === {key} ===", flush=True)
        t_launch = time.time()
        rc = subprocess.run([sys.executable, "run_scenario.py"] + scenario_args(r, args.quick, args.jmeter_bin)).returncode
        events = sorted(
            (p for p in glob.glob("data/*_events.json") if os.path.getmtime(p) >= t_launch),
            key=os.path.getmtime)
        entry = {"key": key, "scenario": r["scenario"], "ok": False, "events": None, "dataset": None}
        if rc != 0 or not events:
            print(f"[error] run_scenario fallo (codigo {rc})")
        else:
            ev_path = events[-1]
            rc2 = subprocess.run([sys.executable, "export_dataset.py", ev_path,
                                  "--warmup", str(1 if args.quick else args.warmup)]).returncode
            ds = ev_path.replace("_events.json", "_dataset.csv")
            if rc2 == 0 and os.path.exists(ds):
                q = baseline_ok(pd.read_csv(ds))
                ev = json.load(open(ev_path))
                entry.update(ok=True, events=ev_path, dataset=ds, baseline_ok=q,
                             recovery_seconds=ev.get("recovery_seconds"))
                if q is False:
                    print("[AVISO] baseline inestable: el run queda marcado como sospechoso")
            else:
                print(f"[error] export_dataset fallo (codigo {rc2})")
        entries[key] = entry
        json.dump(list(entries.values()), open(manifest_path, "w"), indent=2)
        bad_streak = bad_streak + 1 if not entry["ok"] or entry.get("baseline_ok") is False else 0
        if bad_streak >= MAX_BAD_RUNS:
            sys.exit(f"[DETENIDA] {bad_streak} runs malos seguidos: el sistema no esta sano y seguir generaria datos "
                     "inutiles. Revisa los servicios (docker compose restart) y continua con --resume.")
        if i < len(runs):
            time.sleep(1 if args.quick else args.cooldown)

    manifest = list(entries.values())
    frames = []
    for m in manifest:
        if m.get("ok") and m.get("dataset") and os.path.exists(m["dataset"]):
            f = pd.read_csv(m["dataset"])
            f["run_ok"] = m.get("baseline_ok")
            frames.append(f)
    if not frames:
        print("No hay datasets para unir.")
        return
    out = os.path.join("data", f"campaign_{stamp}.csv")
    allf = pd.concat(frames, ignore_index=True)
    allf.to_csv(out, index=False)
    json.dump(manifest, open(out.replace(".csv", "_manifest.json"), "w"), indent=2)
    print(f"\nCampana lista: {len(frames)} runs, {len(allf)} filas -> {out}")
    print(allf.groupby(["scenario", "severity", "phase"]).size().unstack(fill_value=0).to_string())
    bad = [m["key"] for m in manifest if not m.get("ok") or m.get("baseline_ok") is False]
    if bad:
        print("\nRuns a revisar (fallidos o baseline inestable):", ", ".join(bad))


if __name__ == "__main__":
    main()
