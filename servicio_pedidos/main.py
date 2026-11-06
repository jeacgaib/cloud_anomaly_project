import asyncio
import os
import random
import threading
import time

import asyncpg
import httpx
from fastapi import FastAPI, Response
from prometheus_client import Counter, Histogram, make_asgi_app

PAGOS_URL = os.getenv("PAGOS_URL", "http://servicio_pagos:8000/procesar")
PAGOS_TIMEOUT = float(os.getenv("PAGOS_TIMEOUT", "3"))
NOTIF_URL = os.getenv("NOTIF_URL", "http://servicio_notificaciones:8000/notificar")
DB_DSN = os.getenv("DB_DSN", "postgresql://app:app@postgres:5432/cloud")
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

app = FastAPI()
app.mount("/metrics", make_asgi_app())

REQUEST_COUNT = Counter(
    "pedidos_requests_total", "Total de peticiones", ["method", "endpoint", "status"]
)
REQUEST_ERRORS = Counter(
    "pedidos_errors_total", "Peticiones fallidas (BD, pagos, notificaciones o timeout)"
)
REQUEST_LATENCY = Histogram(
    "pedidos_request_latency_seconds", "Latencia total de la peticion", buckets=BUCKETS
)

# Timeouts explicitos de httpx con espera de pool corta. No envolver las llamadas en asyncio.wait_for: cancelar
# mientras se abre una conexion deja su plaza del pool ocupada para siempre y Pedidos acaba en PoolTimeout.
# max_keepalive_connections = max_connections: httpcore cierra conexiones inactivas en cuanto el TOTAL de conexiones
# supera ese limite; con 50, bajo latencia cada peticion abria una conexion nueva y el retardo de netem se duplicaba.
client = httpx.AsyncClient(
    timeout=httpx.Timeout(PAGOS_TIMEOUT, pool=2.0),
    limits=httpx.Limits(max_connections=300, max_keepalive_connections=300, keepalive_expiry=5.0),
)
pool = None

# ---- inyeccion de CPU overload (solo para el experimento) ----------------
_stop_burn = threading.Event()


def _burn(deadline: float, duty: float) -> None:
    """Consume ~`duty` de un nucleo: ciclos de 100 ms, `duty` ocupado y el resto dormido."""
    cycle, x = 0.1, 1.0
    while time.time() < deadline and not _stop_burn.is_set():
        busy_until = time.time() + cycle * duty
        while time.time() < busy_until:
            for _ in range(2000):
                x = (x * 1.000001 + 1.0) % 1000003.0
        if duty < 1.0:
            time.sleep(cycle * (1.0 - duty))


@app.post("/admin/cpu")
def admin_cpu(seconds: int = 60, workers: int = 1, duty: float = 0.4):
    _stop_burn.clear()
    duty = min(1.0, max(0.05, duty))
    deadline = time.time() + seconds
    for _ in range(max(1, workers)):
        threading.Thread(target=_burn, args=(deadline, duty), daemon=True).start()
    return {"cpu_burn": True, "seconds": seconds, "workers": workers, "duty": duty}


@app.post("/admin/reset")
def admin_reset():
    _stop_burn.set()
    return {"cpu_burn": False}


@app.on_event("startup")
async def startup():
    global pool
    for _ in range(30):
        try:
            pool = await asyncpg.create_pool(DB_DSN, min_size=10, max_size=10, command_timeout=5)
            return
        except Exception:
            await asyncio.sleep(1)


@app.on_event("shutdown")
async def shutdown():
    await client.aclose()
    if pool:
        await pool.close()


@app.get("/health")
async def health():
    return {"estado": "ok", "db": pool is not None}


@app.post("/pedido")
async def crear_pedido(response: Response):
    start = time.perf_counter()
    status_code = 200
    try:
        usuario_id = random.randint(1, 100)
        total = round(random.uniform(5, 200), 2)
        async with pool.acquire(timeout=3) as con:
            pedido_id = await con.fetchval(
                "INSERT INTO pedidos (usuario_id, total) VALUES ($1, $2) RETURNING id",
                usuario_id, total,
            )
        r = await client.post(PAGOS_URL, json={"pedido_id": pedido_id, "monto": total})
        r.raise_for_status()
        n = await client.post(NOTIF_URL, json={"pedido_id": pedido_id, "usuario_id": usuario_id})
        n.raise_for_status()
        body = {"servicio": "Pedidos", "estado": "ok", "pedido_id": pedido_id, "pagos": r.json()}
    except Exception as e:
        status_code = 502
        REQUEST_ERRORS.inc()
        body = {"servicio": "Pedidos", "estado": "error", "detalle": str(e) or type(e).__name__}
    REQUEST_LATENCY.observe(time.perf_counter() - start)
    REQUEST_COUNT.labels("POST", "/pedido", str(status_code)).inc()
    response.status_code = status_code
    return body
