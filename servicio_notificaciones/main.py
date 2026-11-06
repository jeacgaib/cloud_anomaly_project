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
    "notificaciones_requests_total", "Total de peticiones", ["method", "endpoint", "status"]
)
REQUEST_ERRORS = Counter("notificaciones_errors_total", "Peticiones fallidas en notificaciones")
REQUEST_LATENCY = Histogram(
    "notificaciones_request_latency_seconds", "Latencia de la peticion", buckets=BUCKETS
)

pool = None


class Notificacion(BaseModel):
    pedido_id: int
    usuario_id: int


@app.on_event("startup")
async def startup():
    global pool
    for _ in range(30):
        try:
            pool = await asyncpg.create_pool(DB_DSN, min_size=5, max_size=10, command_timeout=5)
            break
        except Exception:
            await asyncio.sleep(1)
    if pool:   # por si el volumen de PostgreSQL es anterior a este servicio (init.sql solo corre la primera vez)
        await pool.execute(
            "CREATE TABLE IF NOT EXISTS notificaciones (id SERIAL PRIMARY KEY, pedido_id INT NOT NULL, "
            "usuario_id INT NOT NULL, canal TEXT NOT NULL, creado TIMESTAMPTZ DEFAULT now())"
        )


@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()


@app.get("/health")
async def health():
    return {"estado": "ok", "db": pool is not None}


@app.post("/notificar")
async def notificar(n: Notificacion):
    start = time.perf_counter()
    status = "200"
    try:
        await asyncio.sleep(random.uniform(0.002, 0.008))   # simula el envio (email)
        async with pool.acquire(timeout=3) as con:
            await con.execute(
                "INSERT INTO notificaciones (pedido_id, usuario_id, canal) VALUES ($1, $2, 'email')",
                n.pedido_id, n.usuario_id,
            )
        return {"servicio": "Notificaciones", "estado": "enviada"}
    except Exception:
        status = "500"
        REQUEST_ERRORS.inc()
        raise
    finally:
        REQUEST_LATENCY.observe(time.perf_counter() - start)
        REQUEST_COUNT.labels("POST", "/notificar", status).inc()
