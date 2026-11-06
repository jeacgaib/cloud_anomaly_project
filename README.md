# Explainable Cloud Anomaly Detection

Detección de anomalías en una arquitectura de microservicios en contenedores y primera explicación de **qué
servicio y qué métricas** están asociados a cada anomalía. Se construye un escenario cloud reproducible, se
inyectan fallas controladas (CPU overload y latencia de red), se recolectan métricas con Prometheus y se
compara un baseline (**Isolation Forest**) con una primera solución de IA (**Autoencoder + XAI inicial**).




## 1. Arquitectura
```
Generador de tráfico ──▶ Nginx (:8000) ─┬─▶ servicio_pedidos ─┬─▶ servicio_pagos ──────────┐
 (JMeter / run_scenario)                │                     ├─▶ servicio_notificaciones ─┤
                                        │                     └────────────────────────────┤
                                        └─▶ servicio_usuarios ─────────────────────────────┴─▶ PostgreSQL

Métricas: Prometheus ◀─ /metrics de cada servicio + nginx_exporter + docker_exporter (CPU/RAM por contenedor)
Fallas:   CPU overload en servicio_pedidos  ·  latencia en el enlace Pedidos→Pagos (tc netem dirigido)
```
- `POST /pedido`: Pedidos inserta en PostgreSQL, llama a Pagos (inserta el pago) y después a Notificaciones
  (registra el aviso al usuario). Si Pagos o Notificaciones fallan, el pedido devuelve 502 y cuenta como error.
- `GET /usuarios/{id}`: Usuarios consulta PostgreSQL. No se toca con las fallas: sirve de control.
- Todo el tráfico de prueba entra por Nginx (`http://localhost:8000`); mezcla 80 % pedidos / 20 % usuarios.

| Componente | Puerto host | Uso |
|---|---|---|
| nginx | 8000 | punto de entrada del tráfico |
| servicio_pagos | 8001 | `/admin/latency` y pruebas directas |
| servicio_pedidos | 8002 | `/admin/cpu` y pruebas directas |
| servicio_usuarios | 8003 | pruebas directas |
| servicio_notificaciones | 8004 | pruebas directas |
| Prometheus | 9090 | métricas (retención 7 días) |

Los `/admin/*` no pasan por Nginx a propósito: solo sirven para inyectar fallas.

## 2. Estructura del repositorio
```
docker-compose.yml          escenario completo (9 contenedores)
nginx/  postgres/  prometheus/  monitor/docker_exporter.py  jmeter/plan.jmx
servicio_pedidos/  servicio_pagos/  servicio_usuarios/  servicio_notificaciones/   microservicios FastAPI
run_scenario.py             un run: carga + falla + etiquetas (events.json)
export_dataset.py           Prometheus -> CSV etiquetado de un run
run_campaign.py             campaña completa: muchos runs + CSV unificado
anomaly_models.py           Scaler, Isolation Forest, Autoencoder (compartido)
evaluate.py                 validación cruzada y comparación -> results/
train_final.py              entrena y guarda los modelos finales -> models/
detect.py                   puntúa un CSV nuevo y explica cada anomalía
data/  results/  models/    dataset, resultados y modelos entrenados
```

## 3. Requisitos
- Docker con Compose, Python 3.10+, Java y Apache JMeter (`jmeter -v`; en Windows el comando es `jmeter.bat`).
- Host: `pip install -r requirements-host.txt` (requests, pandas, scikit-learn, matplotlib; `joblib` viene con scikit-learn).
- JMeter, Docker y los contenedores comparten máquina: con cargas altas vigila el CPU del host y anótalo en el informe.

## 4. Reproducir el experimento

### 4.1 Levantar el escenario
```bash
docker compose up -d --build --remove-orphans
docker compose ps
curl http://localhost:8000/health
curl -X POST http://localhost:8000/pedido
curl http://localhost:8000/usuarios/7
```
En `http://localhost:9090/targets` deben estar en UP: nginx, servicio_pedidos, servicio_pagos, servicio_usuarios,
servicio_notificaciones y docker_exporter. La consulta `dockerstats_cpu_cores` debe devolver una serie por contenedor.

### 4.2 Un run suelto
```bash
python run_scenario.py --scenario normal  --rps 50 --duration 600
python run_scenario.py --scenario cpu     --cpu-duty 0.4
python run_scenario.py --scenario latency --latency-ms 300
python export_dataset.py data/<run_id>_events.json --warmup 80
```
Valores por defecto: 50 rps, 200 hilos, rampa 30 s, baseline 180 s, falla 120 s, recuperación hasta 120 s.
- **cpu**: un hilo en `servicio_pedidos` que consume `--cpu-duty` de un núcleo. Pedidos tiene límite de 1.0 CPU y usa
  ~0.30 en reposo (con Notificaciones). Medido: duty 0.6 lleva el CPU a ~0.86 sin errores; duty 0.8 lo colapsa (latencia
  de ~5 s y ~6 errores/s), porque el hilo de la falla comparte el GIL con el servicio y la suma supera un núcleo. Por eso
  la campaña usa duty 0.2 / 0.4 / 0.5 / 0.6.
- **latency**: `tc netem` **dirigido solo al tráfico Pedidos→Pagos** (filtro por IP destino); la BD no se afecta. Si el
  kernel no lo soporta, cae a retardo en la aplicación y lo avisa; el modo usado queda en `events.json`. Pedidos reutiliza
  las conexiones a Pagos (`max_keepalive_connections` = `max_connections`); si abriera una por petición, la apertura también
  pagaría el retardo y la latencia inyectada se duplicaría.
- Antes de cada run se vacían `pedidos`, `pagos` y `notificaciones` (`--no-reset-db` lo desactiva) para evitar deriva del baseline.
- Tras la falla, una sonda mide cuándo se recupera el sistema (`recovered_at`, `recovery_seconds`).
- **Criterio de calidad de un run:** durante `baseline` la latencia de Pedidos debe ser estable (~30-40 ms con Notificaciones, p95 < 100 ms,
  0 errores). Si no, el run no sirve como "normal".

### 4.3 Campaña completa (recomendado)
```bash
python run_campaign.py --dry-run        # plan y tiempo estimado
python run_campaign.py --repeats 3      # 24 runs, ~3.5 h
python run_campaign.py --resume         # continúa si se interrumpe
```
Plan: normal a 30/50/70 rps (10 min), CPU con duty 0.2/0.4/0.5/0.6 y latencia 100/300/500 ms, 3 repeticiones por falla,
en orden mezclado. Por run: vacía tablas, ejecuta el escenario, exporta el dataset y comprueba la estabilidad del baseline
(`run_ok`). Salida: `data/campaign_<fecha>.csv` y `_manifest.json`.

### 4.4 Evaluar, entrenar y detectar
```bash
python evaluate.py data/campaign_<fecha>.csv --out results      # comparación IF vs Autoencoder
python train_final.py data/campaign_<fecha>.csv                 # guarda models/model_bundle.joblib
python detect.py data/<run_id>_dataset.csv                      # puntúa y explica un CSV nuevo
```
`detect.py` escribe `<entrada>_detect.csv` (puntuación y marca por fila) y `<entrada>_events.csv` (un evento por anomalía
confirmada, con el componente y las variables señaladas). Con `--model autoencoder|isolation_forest` usa un solo modelo.

**Importante:** los modelos guardados dependen de la versión de scikit-learn (se registra en `models/metadata.json`).
Si `detect.py` falla al cargarlos o tu versión es otra, reentrena en tu máquina con `train_final.py` (pocos minutos).

## 5. Dataset
Una fila cada 5 s por run. Columnas por componente (`nginx_*`, `pedidos_*`, `usuarios_*`, `pagos_*`, `notificaciones_*`,
`postgres_*`):
`cpu_cores`, `ram_mb`, `cpu_throttled_ps`, y según el caso `latency_ms`, `latency_p95_ms`, `rps`, `errors_ps`, `conn_active`.
Etiquetas y agrupación: `label` (1 = falla activa), `phase`, `run_id`, `scenario`, `severity` (duty o ms), `rps_target`, `run_ok`.
- `phase`: `warmup | baseline | fault | recovery | post`. Excluye `warmup` y `recovery` al entrenar y evaluar: las tasas usan
  ventanas de 15 s, así que las latencias tardan ~10 s en reflejar el inicio de la falla y ~15 s en normalizarse al terminar.
- `latency_*` queda vacía si en la ventana no terminó ninguna petición (no se rellena).
- Para modelar se usan **24 variables**: se excluyen la RAM absoluta (deriva entre runs), `nginx_conn_active` (= hilos de
  JMeter) y las columnas constantes. Lista en `models/metadata.json`.
- Divide train/test **por `run_id`**, nunca por filas (las filas consecutivas están muy correlacionadas).

## 6. Modelos y protocolo de evaluación
- **Isolation Forest** (baseline): 300 árboles. No trae atribución por variable: se usa |z| (desviación estandarizada) como
  sustituto; no es una explicación propia del modelo.
- **Autoencoder**: red densa 16-6-16 (`MLPRegressor` de scikit-learn, tanh, 3 semillas promediadas), entrenada solo con
  filas normales. Puntuación = error de reconstrucción; **explicación** = error de reconstrucción por variable, normalizado con
  el error típico en datos normales y agregado por componente.
- **Protocolo**: validación cruzada K=3 agrupada por run; umbral = percentil 95 de las puntuaciones fuera de muestra sobre
  normales de entrenamiento; **alerta = 2 filas consecutivas** sobre el umbral. El tiempo de detección se mide desde el inicio
  exacto de la falla (columna `fault_start`), con resolución de 5 s.
- **Métricas**: P/R/F1 por severidad usan las filas de los runs de esa falla; la fila **TODAS** usa todos los runs, incluidos
  los normales, así que sus falsos positivos sí cuentan. La explicación se evalúa solo sobre las filas de falla que el modelo
  marcó: una falla no detectada no tiene explicación.

## 7. Resultados

| Métrica | Isolation Forest | Autoencoder |
|---|---|---|
| F1 por fila (todos los runs) | 0,080 | **0,752** |
| Precisión / Recall | 0,319 / 0,046 | 0,765 / 0,738 |
| AUC por severidad | 0,86-1,00 | 0,98-1,00 |
| Fallas detectadas (de 21 runs) | 2 | **17** |
| Tiempo de detección mediano | 62 s (dos runs) | **14 s** |
| Falsas alarmas por hora | 5,51 | **1,84** |
| Filas marcadas en runs normales (30/50/70 rps) | 13,0 % | 34,6 % |
| Runs con filas de falla marcadas (se pueden explicar) | 4 de 21 | 18 de 21 |
| Servicio correcto señalado (Pedidos), sobre esos runs | 4 de 4 | 14 de 18 |
| Variable esperada entre las 3 primeras, sobre esos runs | 4 de 4 | 16 de 18 |

- **Autoencoder:** F1 ≥ 0,95 en CPU 0,5 / 0,6 y en latencia 100 / 300 / 500 ms. Falla en las fallas sutiles: CPU 0,4 (F1 0,47; 2 de
  3 runs) y CPU 0,2 (F1 0,03; 0 de 3). Marca el **100 % del run normal a 30 rps**, una carga que no vio al entrenar.
- **Isolation Forest:** ordena bien las filas, pero con el umbral calibrado casi no alerta en las fallas. Marca el 38 % del run
  normal a 70 rps. Barrer el umbral no lo arregla: su mejor F1 (0,74, con etiquetas de test) marca el 68 % de las filas normales.
- **El problema principal es el umbral.** Las filas de los runs normales a 30 y 70 rps, con cargas no vistas, deciden el percentil 95:
  el umbral del Autoencoder es de 1,5 a 5,4 según el fold, cuando con solo las filas a 50 rps sería de 0,11 a 0,18.
- **Explicación:** el Autoencoder señala Pedidos en 14 de 18 runs. Los errores vienen de la falla sutil (CPU 0,2) y de variables de
  throttling casi siempre a 0, que saturan el escalado con un solo valor aislado. La variable señalada refleja la **mayor desviación,
  no la causa raíz**. Eso motiva las explicaciones topológicas y temporales del P2.
- **Sensibilidad (exploratorio, después de ver resultados):** sin las variables de throttling (`evaluate.py --sin-throttled`, en
  `results/variante_sin_throttled/`), el F1 baja a 0,70 y el servicio correcto sube a 16 de 16.
- Figuras: `informe/graficos/` (se generan con `informe/generar_graficos.py`) y `results/fig_*.png`. Tablas en `results/summary.md`.
  Ejemplo de `detect.py` con runs no vistos en `results/ejemplo_deteccion/`: se entrenó sin `20261105_171438_latency`,
  `20261105_173740_cpu` y `20261105_193850_normal` (`train_final.py --exclude-runs ... --out models_ejemplo`). El Autoencoder detecta la
  falla de latencia y señala Pedidos; en CPU 0,4 alerta solo 10 s y señala erróneamente a Notificaciones; el run normal no da alertas.
  Isolation Forest no marca nada.

### 8. Limitaciones
- El banco de pruebas es limpio y corre en una sola máquina: los resultados son preliminares.
- Solo hay 3 runs normales (30/50/70 rps): un solo run por carga, por lo que cada carga se evalúa sin haberla visto al entrenar.
- Las fallas solo se inyectan en Pedidos (CPU) y en el enlace Pedidos→Pagos: "señala Pedidos" no demuestra todavía que la
  explicación localice fallas en otros servicios.
- Hubo colapsos espontáneos de Pedidos sin falla inyectada (causa sin demostrar; hay indicios de un pico de CPU en PostgreSQL). El run
  afectado se repitió, así que no están en el dataset final y las falsas alarmas reales podrían ser mayores.
- CPU 0,6 está en el límite de saturación: colapsó durante la falla en 1 de 3 runs (hasta 9,6 s). Sigue en el dataset.
- Una sola campaña (3 repeticiones por falla); el Autoencoder llega al máximo de 800 iteraciones sin converger del todo
  (pérdida final ~0,045) y es una primera versión; la versión PyTorch y la GNN quedan para el P2.
- Nginx solo expone requests/s y conexiones: los 504 que ve el cliente solo están en el `.jtl` de JMeter, no en el dataset.
- El generador es de lazo cerrado: si el sistema se ralentiza, JMeter envía menos peticiones (usa `--threads` ≥ rps × latencia).
- Los modelos guardados dependen de la versión de scikit-learn.



## 9. Problemas frecuentes
- **No encuentro JMeter:** añade `<JMETER>/bin` al PATH o usa `--jmeter-bin` (en `run_scenario.py` y en `run_campaign.py`).
- **Aviso "netem dirigido no disponible":** se usó latencia a nivel de aplicación (queda en `events.json`).
- **`dockerstats_cpu_cores` vacío:** revisa `docker compose logs docker_exporter` y que se monte `/var/run/docker.sock`.
- **Un run sale con latencias de segundos en `baseline`:** el sistema está saturado; descártalo (`run_ok = False`) y repítelo.
- **La campaña se detiene con `[DETENIDA]`:** hubo 2 runs malos seguidos (fallidos o con baseline inestable). Ejecuta
  `docker compose restart`, comprueba que `POST /pedido` responde en ~40 ms y continúa con `--resume`, que repite esos runs.
- **Faltan datos antiguos en Prometheus:** retiene 7 días; exporta cada run poco después de hacerlo.
- **`detect.py` no carga el modelo:** versión distinta de scikit-learn; ejecuta `train_final.py`.
- **Falta la tabla `notificaciones`:** si el volumen de PostgreSQL es anterior al servicio, `init.sql` no se vuelve a ejecutar;
  Notificaciones la crea al arrancar. Si aun así falla, `docker compose restart servicio_notificaciones`.

