import asyncio
import os
import random
import time

import asyncpg
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel

DB_DSN = os.getenv("DB_DSN", "postgresql://app:app@postgres:5432/cloud")
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

app = FastAPI()
app.mount("/metrics", make_asgi_app())

REQUEST_COUNT = Counter(
    "pagos_requests_total", "Total de peticiones", ["method", "endpoint", "status"]
)
REQUEST_ERRORS = Counter("pagos_errors_total", "Peticiones fallidas en pagos")
REQUEST_LATENCY = Histogram(
    "pagos_request_latency_seconds", "Latencia de la peticion", buckets=BUCKETS
)

state = {"latency_ms": 0}  # latencia a nivel de app (alternativa a tc netem)
pool = None


class Pago(BaseModel):
    pedido_id: int
    monto: float


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
    if pool:
        await pool.close()


@app.get("/health")
async def health():
    return {"estado": "ok", "db": pool is not None}


@app.post("/procesar")
async def procesar_pago(pago: Pago):
    start = time.perf_counter()
    status = "200"
    try:
        await asyncio.sleep(random.uniform(0.005, 0.020) + state["latency_ms"] / 1000.0)
        async with pool.acquire(timeout=3) as con:
            await con.execute(
                "INSERT INTO pagos (pedido_id, monto, estado) VALUES ($1, $2, 'aprobado')",
                pago.pedido_id, pago.monto,
            )
        return {"servicio": "Pagos", "estado": "procesado"}
    except Exception:
        status = "500"
        REQUEST_ERRORS.inc()
        raise
    finally:
        REQUEST_LATENCY.observe(time.perf_counter() - start)
        REQUEST_COUNT.labels("POST", "/procesar", status).inc()


@app.post("/admin/latency")
def admin_latency(ms: int = 0):
    state["latency_ms"] = max(0, ms)
    return dict(state)


@app.post("/admin/reset")
def admin_reset():
    state["latency_ms"] = 0
    return dict(state)
