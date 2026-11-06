"""Exporter de metricas por contenedor leyendo la API de Docker (socket unix).

Sustituye a cAdvisor, que en Docker Desktop/WSL2 solo ve el cgroup raiz.
Metricas (etiqueta container = nombre del contenedor):
  dockerstats_cpu_cores                       CPU usada, en nucleos
  dockerstats_memory_mb                       memoria usada (MB, sin cache)
  dockerstats_cpu_throttled_periods_total     periodos CFS limitados (acumulado)
  dockerstats_network_rx_bytes_total / _tx_   trafico de red (acumulado)
"""
import http.client
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from prometheus_client import Gauge, start_http_server

SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")
INTERVAL = float(os.getenv("INTERVAL", "3"))
PORT = int(os.getenv("PORT", "9200"))

CPU = Gauge("dockerstats_cpu_cores", "CPU usada (nucleos)", ["container"])
MEM = Gauge("dockerstats_memory_mb", "Memoria usada (MB)", ["container"])
THR = Gauge("dockerstats_cpu_throttled_periods_total", "Periodos CFS limitados", ["container"])
RX = Gauge("dockerstats_network_rx_bytes_total", "Bytes recibidos", ["container"])
TX = Gauge("dockerstats_network_tx_bytes_total", "Bytes enviados", ["container"])


class UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout=15):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def api(path):
    c = UnixConn(SOCK)
    try:
        c.request("GET", path)
        return json.loads(c.getresponse().read())
    finally:
        c.close()


def parse(s):
    """Convierte la respuesta de /containers/<id>/stats en valores simples."""
    cpu, pre = s["cpu_stats"], s.get("precpu_stats", {})
    cpu_delta = cpu["cpu_usage"]["total_usage"] - pre.get("cpu_usage", {}).get("total_usage", 0)
    sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    ncpu = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
    cores = cpu_delta / sys_delta * ncpu if sys_delta > 0 and cpu_delta >= 0 else 0.0
    mem = s.get("memory_stats", {})
    st = mem.get("stats", {})
    used = mem.get("usage", 0) - st.get("inactive_file", st.get("cache", 0))
    nets = s.get("networks", {}).values()
    return {
        "cpu": cores,
        "mem_mb": max(used, 0) / 1e6,
        "throttled": cpu.get("throttling_data", {}).get("throttled_periods", 0),
        "rx": sum(n.get("rx_bytes", 0) for n in nets),
        "tx": sum(n.get("tx_bytes", 0) for n in nets),
    }


def one(container):
    name = container["Names"][0].lstrip("/")
    try:
        v = parse(api(f"/containers/{container['Id']}/stats?stream=false"))
    except Exception as e:
        print(f"[aviso] {name}: {e}", flush=True)
        return
    CPU.labels(name).set(v["cpu"])
    MEM.labels(name).set(v["mem_mb"])
    THR.labels(name).set(v["throttled"])
    RX.labels(name).set(v["rx"])
    TX.labels(name).set(v["tx"])


def loop():
    while True:
        t0 = time.time()
        try:
            containers = api("/containers/json")
            with ThreadPoolExecutor(max_workers=16) as ex:
                list(ex.map(one, containers))
        except Exception as e:
            print(f"[error] {e}", flush=True)
        time.sleep(max(0.0, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    start_http_server(PORT)
    print(f"docker_exporter en :{PORT} (socket {SOCK})", flush=True)
    threading.Thread(target=loop, daemon=True).start()
    while True:
        time.sleep(3600)
