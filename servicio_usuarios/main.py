import asyncio
import os
import time

import asyncpg
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, make_asgi_app

DB_DSN = os.getenv("DB_DSN", "postgresql://app:app@postgres:5432/cloud")
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

app = FastAPI()
app.mount("/metrics", make_asgi_app())

REQUEST_COUNT = Counter(
    "usuarios_requests_total", "Total de peticiones", ["method", "endpoint", "status"]
)
REQUEST_ERRORS = Counter("usuarios_errors_total", "Peticiones fallidas (5xx) en usuarios")
REQUEST_LATENCY = Histogram(
    "usuarios_request_latency_seconds", "Latencia de la peticion", buckets=BUCKETS
)

pool = None


@app.on_event("startup")
async def startup():
    global pool
    for _ in range(30):
        try:
            pool = await asyncpg.create_pool(DB_DSN, min_size=5, max_size=10, command_timeout=5)
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


@app.get("/usuarios/{usuario_id}")
async def obtener_usuario(usuario_id: int):
    start = time.perf_counter()
    status = "200"
    try:
        async with pool.acquire(timeout=3) as con:
            row = await con.fetchrow(
                "SELECT id, nombre, email FROM usuarios WHERE id = $1", usuario_id
            )
        if row is None:
            status = "404"
            raise HTTPException(status_code=404, detail="usuario no encontrado")
        return {"servicio": "Usuarios", **dict(row)}
    except HTTPException:
        raise
    except Exception:
        status = "500"
        REQUEST_ERRORS.inc()
        raise
    finally:
        REQUEST_LATENCY.observe(time.perf_counter() - start)
        REQUEST_COUNT.labels("GET", "/usuarios/{id}", status).inc()
