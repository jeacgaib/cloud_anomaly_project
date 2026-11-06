#!/usr/bin/env python3
"""Genera trafico, inyecta la falla del escenario y guarda las etiquetas.

Escenarios:
  normal   -> solo trafico, sin fallas
  cpu      -> CPU overload en servicio_pedidos
  latency  -> latencia en el enlace Pedidos->Pagos (tc netem dirigido en Pedidos, o a nivel de app)

Generadores de trafico (--generator):
  jmeter   -> Apache JMeter en modo no-GUI con jmeter/plan.jmx (recomendado)
  python   -> script con hilos (solo para pruebas rapidas, techo de carga bajo)

Salida (carpeta data/):
  <run_id>_jmeter.jtl | <run_id>_requests.csv   traza de peticiones del generador
  <run_id>_events.json                           ground truth: inicio/fin de la falla
"""
import argparse
import csv
import json
import os
import random
import shutil
import subprocess
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")  # Nginx (punto de entrada)
PEDIDOS_ADMIN = os.getenv("PEDIDOS_ADMIN", "http://localhost:8002/admin")
PAGOS_ADMIN = os.getenv("PAGOS_ADMIN", "http://localhost:8001/admin")
PAGOS_CONTAINER = "servicio_pagos"
PEDIDOS_CONTAINER = "servicio_pedidos"
JMX_PLAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jmeter", "plan.jmx")


# ------------------------------------------------------------------ generadores
def python_worker(stop, mean_gap, writer, lock):
    session = requests.Session()
    while not stop.is_set():
        t0 = time.time()
        try:
            if random.random() < 0.8:   # mezcla: 80% pedidos, 20% consultas de usuario
                status = session.post(f"{BASE_URL}/pedido", timeout=10).status_code
            else:
                uid = random.randint(1, 100)
                status = session.get(f"{BASE_URL}/usuarios/{uid}", timeout=10).status_code
        except requests.RequestException:
            status = 0
        lat_ms = (time.time() - t0) * 1000
        with lock:
            writer.writerow([f"{t0:.3f}", status, f"{lat_ms:.1f}"])
        stop.wait(random.expovariate(1.0 / mean_gap))


class PythonLoad:
    def __init__(self, args, trace_path):
        self.stop_evt, self.lock = threading.Event(), threading.Lock()
        self.file = open(trace_path, "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["timestamp", "status", "latency_ms"])
        gap = args.threads / args.rps
        self.threads = [threading.Thread(target=python_worker,
                                         args=(self.stop_evt, gap, self.writer, self.lock), daemon=True)
                        for _ in range(args.threads)]
        self.trace = trace_path

    def start(self):
        for t in self.threads:
            t.start()

    def stop(self):
        self.stop_evt.set()
        for t in self.threads:
            t.join(timeout=12)
        self.file.close()


class JMeterLoad:
    def __init__(self, args, trace_path, total_seconds):
        exe = args.jmeter_bin or shutil.which("jmeter") or shutil.which("jmeter.bat")
        if not exe:
            raise SystemExit("No encuentro JMeter. Anade <JMETER>/bin al PATH o usa --jmeter-bin.")
        u = urlparse(BASE_URL)
        self.total = total_seconds
        self.trace = trace_path
        self.log_path = trace_path.replace(".jtl", ".log")
        self.cmd = [
            exe, "-n", "-t", JMX_PLAN, "-l", trace_path,
            f"-Jhost={u.hostname}", f"-Jport={u.port or 80}",
            f"-Jthreads={args.threads}", f"-Jrampup={args.rampup}",
            f"-Jduration={total_seconds}", f"-Jtpm={int(args.rps * 60)}",
        ]
        self.proc = None

    def start(self):
        self.log = open(self.log_path, "w")
        self.proc = subprocess.Popen(self.cmd, stdout=self.log, stderr=subprocess.STDOUT)

    def stop(self):
        try:
            self.proc.wait(timeout=45)   # JMeter termina solo al acabar la duracion
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=15)
        self.log.close()


# ------------------------------------------------------------------ fallas
def _tc(cmd, check=True):
    """Ejecuta un comando dentro del contenedor de Pedidos."""
    return subprocess.run(["docker", "exec", PEDIDOS_CONTAINER, "sh", "-c", cmd],
                          check=check, capture_output=True, text=True)


def netem_on(delay_ms):
    """Retardo SOLO en el trafico Pedidos -> Pagos (filtro por IP destino).
    El resto del trafico (BD, Nginx) no se ve afectado."""
    ip = subprocess.run(
        ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", PAGOS_CONTAINER],
        check=True, capture_output=True, text=True).stdout.strip()
    _tc("tc qdisc del dev eth0 root 2>/dev/null; true", check=False)
    _tc("tc qdisc add dev eth0 root handle 1: prio bands 3 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1")
    _tc(f"tc qdisc add dev eth0 parent 1:3 handle 30: netem delay {delay_ms}ms")
    _tc(f"tc filter add dev eth0 protocol ip parent 1: prio 3 u32 match ip dst {ip}/32 flowid 1:3")
    print(f"[netem] +{delay_ms} ms solo hacia Pagos ({ip})")
    return ip


def netem_off():
    _tc("tc qdisc del dev eth0 root 2>/dev/null; true", check=False)


def inject(args):
    if args.scenario == "cpu":
        requests.post(
            f"{PEDIDOS_ADMIN}/cpu",
            params={"seconds": args.fault_duration + 10, "workers": args.cpu_workers, "duty": args.cpu_duty},
            timeout=5,
        ).raise_for_status()
        return {"cpu_workers": args.cpu_workers, "cpu_duty": args.cpu_duty}

    mode = args.latency_mode
    extra = {}
    if mode == "netem":
        try:
            extra["pagos_ip"] = netem_on(args.latency_ms)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[aviso] netem dirigido no disponible ({getattr(e, 'stderr', e)}); uso retardo a nivel de aplicacion")
            mode = "app"
    if mode == "app":
        requests.post(f"{PAGOS_ADMIN}/latency", params={"ms": args.latency_ms}, timeout=5).raise_for_status()
    return {"latency_ms": args.latency_ms, "latency_mode": mode, **extra}


def clear(params):
    for url in (PEDIDOS_ADMIN, PAGOS_ADMIN):
        try:
            requests.post(f"{url}/reset", timeout=5)
        except requests.RequestException:
            pass
    if params.get("latency_mode") == "netem":
        try:
            netem_off()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass


def probe_recovery(result, max_wait):
    """Tras quitar la falla, sondea POST /pedido hasta ver 8 respuestas buenas seguidas
    (200 en < 250 ms). Guarda en result["recovered_at"] el instante de la primera de ellas."""
    t_begin, streak, first_good = time.time(), 0, None
    while time.time() - t_begin < max_wait:
        t = time.time()
        try:
            r = requests.post(f"{BASE_URL}/pedido", timeout=5)
            good = r.status_code == 200 and (time.time() - t) < 0.25
        except requests.RequestException:
            good = False
        if good:
            streak += 1
            first_good = first_good or t
            if streak >= 8:
                result["recovered_at"] = first_good
                return
        else:
            streak, first_good = 0, None
        time.sleep(1)


def wait(seconds, label):
    end = time.time() + seconds
    print(f"[{label}] {seconds}s")
    while time.time() < end:
        time.sleep(min(1.0, max(0.0, end - time.time())))


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scenario", choices=["normal", "cpu", "latency"], required=True)
    ap.add_argument("--generator", choices=["jmeter", "python"], default="jmeter")
    ap.add_argument("--rps", type=float, default=50, help="peticiones/s objetivo")
    ap.add_argument("--threads", type=int, default=None,
                    help="usuarios virtuales (default: jmeter=200, python=8)")
    ap.add_argument("--rampup", type=int, default=30, help="s de rampa de JMeter")
    ap.add_argument("--duration", type=int, default=300, help="duracion (solo normal)")
    ap.add_argument("--baseline", type=int, default=180, help="s normales antes de la falla")
    ap.add_argument("--fault-duration", type=int, default=120, help="s con la falla activa")
    ap.add_argument("--recovery", type=int, default=120, help="s maximos de recuperacion tras la falla")
    ap.add_argument("--cpu-workers", type=int, default=1)
    ap.add_argument("--cpu-duty", type=float, default=0.4,
                    help="fraccion de nucleo que consume cada hilo de CPU overload (0.05-1.0)")
    ap.add_argument("--latency-ms", type=int, default=300)
    ap.add_argument("--latency-mode", choices=["netem", "app"], default="netem")
    ap.add_argument("--reset-db", action=argparse.BooleanOptionalAction, default=True,
                    help="vacia pedidos, pagos y notificaciones antes de cada run (evita deriva del baseline)")
    ap.add_argument("--jmeter-bin", default=None, help="ruta a jmeter / jmeter.bat si no esta en el PATH")
    args = ap.parse_args()
    if args.threads is None:
        args.threads = 200 if args.generator == "jmeter" else 8
    if args.generator == "jmeter" and args.scenario != "normal" and args.baseline < args.rampup:
        print("[aviso] baseline menor que la rampa: la falla empezaria antes de alcanzar la carga objetivo")

    if args.reset_db:
        try:
            subprocess.run(["docker", "exec", "postgres", "psql", "-U", "app", "-d", "cloud", "-c",
                            "TRUNCATE pedidos, pagos, notificaciones RESTART IDENTITY;"],
                           check=True, capture_output=True, text=True)
            print("[db] tablas pedidos, pagos y notificaciones vaciadas")
            time.sleep(5)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[aviso] no pude vaciar las tablas: {getattr(e, 'stderr', e)}")

    os.makedirs("data", exist_ok=True)
    run_id = f"{datetime.now():%Y%m%d_%H%M%S}_{args.scenario}"
    ev_path = os.path.join("data", f"{run_id}_events.json")
    total = args.duration if args.scenario == "normal" else args.baseline + args.fault_duration + args.recovery

    if args.generator == "jmeter":
        trace = os.path.join("data", f"{run_id}_jmeter.jtl")
        load = JMeterLoad(args, trace, total)
    else:
        trace = os.path.join("data", f"{run_id}_requests.csv")
        load = PythonLoad(args, trace)

    params, fault_start, fault_end = {}, None, None
    recovery = {}
    t_start = time.time()
    load.start()
    try:
        if args.scenario == "normal":
            wait(args.duration, "normal")
        else:
            wait(args.baseline, "baseline normal")
            params = inject(args)
            fault_start = time.time()
            wait(args.fault_duration, f"FALLA {args.scenario}")
            fault_end = time.time()
            clear(params)
            probe = threading.Thread(target=probe_recovery, args=(recovery, args.recovery), daemon=True)
            probe.start()
            wait(args.recovery, "recuperacion")
            probe.join(timeout=8)
    finally:
        if args.scenario != "normal" and fault_end is None:
            fault_end = time.time()
            clear(params)
        load.stop()
        t_end = time.time()

    events = {
        "run_id": run_id,
        "scenario": args.scenario,
        "fault_service": {"normal": None, "cpu": "servicio_pedidos",
                          "latency": "enlace_pedidos_pagos"}[args.scenario],
        "t_start": t_start,
        "t_end": t_end,
        "fault_start": fault_start,
        "fault_end": fault_end,
        "recovered_at": recovery.get("recovered_at"),
        "recovery_seconds": (recovery["recovered_at"] - fault_end) if recovery.get("recovered_at") and fault_end else None,
        "generator": args.generator,
        "trace_file": trace,
        "params": {"rps": args.rps, "threads": args.threads, "rampup": args.rampup, **params},
    }
    with open(ev_path, "w") as f:
        json.dump(events, f, indent=2)
    if args.scenario != "normal":
        if recovery.get("recovered_at"):
            print(f"Recuperacion: {events['recovery_seconds']:.0f} s tras quitar la falla")
        else:
            print("[AVISO] el sistema NO se recupero durante la ventana de recuperacion")
    print(f"Listo. Traza: {trace}\nEtiquetas: {ev_path}")


if __name__ == "__main__":
    main()
