# Resultados P1: Isolation Forest vs Autoencoder

- Runs: 24 (cpu: 12, latency: 9, normal: 3); validacion cruzada agrupada por run (K=3).
- Features (20): nginx_cpu_cores, nginx_rps, pedidos_cpu_cores, pedidos_latency_ms, pedidos_latency_p95_ms, pedidos_rps, pedidos_errors_ps, usuarios_cpu_cores, usuarios_latency_ms, usuarios_latency_p95_ms, usuarios_rps, pagos_cpu_cores, pagos_latency_ms, pagos_latency_p95_ms, pagos_rps, notificaciones_cpu_cores, notificaciones_latency_ms, notificaciones_latency_p95_ms, notificaciones_rps, postgres_cpu_cores
- Umbral: percentil 95 fuera de muestra sobre normales de entrenamiento. Alerta = 2 filas consecutivas.
- Resolucion temporal: 5 s (las tasas usan ventanas de 15 s).

## Metricas por fila
Por severidad: filas de los runs de esa falla. TODAS: todos los runs, incluidos los normales.
| modelo | escenario | severidad | precision | recall | f1 | auc | pr_auc | filas_falla |
|---|---|---|---|---|---|---|---|---|
| Isolation Forest | cpu | 0.200 | 0.000 | 0.000 | 0.000 | 0.993 | 0.976 | 72 |
| Isolation Forest | cpu | 0.400 | 0.000 | 0.000 | 0.000 | 0.999 | 0.999 | 72 |
| Isolation Forest | cpu | 0.500 | 0.000 | 0.000 | 0.000 | 0.858 | 0.702 | 72 |
| Isolation Forest | cpu | 0.600 | 0.941 | 0.222 | 0.360 | 0.966 | 0.899 | 72 |
| Isolation Forest | latency | 100.000 | 0.000 | 0.000 | 0.000 | 0.902 | 0.753 | 72 |
| Isolation Forest | latency | 300.000 | 1.000 | 0.014 | 0.027 | 1.000 | 1.000 | 72 |
| Isolation Forest | latency | 500.000 | 1.000 | 0.028 | 0.054 | 0.994 | 0.985 | 72 |
| Isolation Forest | TODAS |  | 0.241 | 0.038 | 0.065 |  |  | 504 |
| Autoencoder | cpu | 0.200 | 0.000 | 0.000 | 0.000 | 0.992 | 0.961 | 72 |
| Autoencoder | cpu | 0.400 | 1.000 | 0.069 | 0.130 | 1.000 | 1.000 | 72 |
| Autoencoder | cpu | 0.500 | 0.979 | 0.639 | 0.773 | 0.989 | 0.978 | 72 |
| Autoencoder | cpu | 0.600 | 0.972 | 0.972 | 0.972 | 0.992 | 0.960 | 72 |
| Autoencoder | latency | 100.000 | 0.986 | 0.986 | 0.986 | 1.000 | 1.000 | 72 |
| Autoencoder | latency | 300.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 72 |
| Autoencoder | latency | 500.000 | 1.000 | 0.972 | 0.986 | 1.000 | 0.999 | 72 |
| Autoencoder | TODAS |  | 0.749 | 0.663 | 0.703 |  |  | 504 |

## Deteccion por evento (run)
| modelo | escenario | severidad | runs | detectadas | t_deteccion_mediana_s |
|---|---|---|---|---|---|
| Autoencoder | cpu | 0.2 | 3 | 0 |  |
| Autoencoder | cpu | 0.4 | 3 | 1 | 69.9 |
| Autoencoder | cpu | 0.5 | 3 | 2 | 14.9 |
| Autoencoder | cpu | 0.6 | 3 | 3 | 14.9 |
| Autoencoder | latency | 100.0 | 3 | 3 | 9.5 |
| Autoencoder | latency | 300.0 | 3 | 3 | 9.4 |
| Autoencoder | latency | 500.0 | 3 | 3 | 14.4 |
| Isolation Forest | cpu | 0.2 | 3 | 0 |  |
| Isolation Forest | cpu | 0.4 | 3 | 0 |  |
| Isolation Forest | cpu | 0.5 | 3 | 0 |  |
| Isolation Forest | cpu | 0.6 | 3 | 1 | 49.9 |
| Isolation Forest | latency | 100.0 | 3 | 0 |  |
| Isolation Forest | latency | 300.0 | 3 | 0 |  |
| Isolation Forest | latency | 500.0 | 3 | 1 | 104.4 |

## Falsas alarmas
| modelo | falsas_alarmas_por_hora | filas_normales_marcadas_pct_runs_normales |
|---|---|---|
| Isolation Forest | 6.73 | 16.51 |
| Autoencoder | 1.84 | 33.97 |

## Sensibilidad del umbral (cota superior, usa etiquetas de test)
Mejor multiplicador del umbral calibrado por modelo y su rendimiento:
| modelo | multiplicador_umbral | precision | recall | f1 | marcadas_pct_en_runs_normales |
|---|---|---|---|---|---|
| Autoencoder | 0.500 | 0.778 | 0.794 | 0.786 | 33.968 |
| Isolation Forest | 0.700 | 0.596 | 0.960 | 0.736 | 68.571 |

## Explicacion (fraccion de runs detectados; solo filas de falla marcadas por el modelo)
| modelo | escenario | severidad | runs_explicados | servicio_ok | variable_ok_top1 | variable_ok_top3 | share_var1 | share_var2 | share_var3 |
|---|---|---|---|---|---|---|---|---|---|
| Autoencoder | cpu | 0.40 | 2 | 1.00 | 1.00 | 1.00 | 0.54 | 0.20 | 0.07 |
| Autoencoder | cpu | 0.50 | 2 | 1.00 | 1.00 | 1.00 | 0.46 | 0.23 | 0.12 |
| Autoencoder | cpu | 0.60 | 3 | 1.00 | 0.33 | 1.00 | 0.34 | 0.29 | 0.18 |
| Autoencoder | latency | 100.00 | 3 | 1.00 | 1.00 | 1.00 | 0.76 | 0.11 | 0.03 |
| Autoencoder | latency | 300.00 | 3 | 1.00 | 1.00 | 1.00 | 0.55 | 0.37 | 0.02 |
| Autoencoder | latency | 500.00 | 3 | 1.00 | 0.67 | 1.00 | 0.69 | 0.24 | 0.02 |
| Isolation Forest | cpu | 0.60 | 1 | 1.00 | 0.00 | 1.00 | 0.30 | 0.27 | 0.09 |
| Isolation Forest | latency | 300.00 | 1 | 1.00 | 1.00 | 1.00 | 0.47 | 0.40 | 0.03 |
| Isolation Forest | latency | 500.00 | 1 | 1.00 | 1.00 | 1.00 | 0.46 | 0.39 | 0.03 |

## Variables mas señaladas
| modelo | escenario | severidad | top1_mas_frecuente | top2 | top3 |
|---|---|---|---|---|---|
| Autoencoder | cpu | 0.400 | pedidos_cpu_cores | pedidos_latency_ms | usuarios_cpu_cores |
| Autoencoder | cpu | 0.500 | pedidos_cpu_cores | pedidos_latency_ms | pedidos_latency_p95_ms |
| Autoencoder | cpu | 0.600 | pedidos_latency_ms | pedidos_cpu_cores | pedidos_latency_p95_ms |
| Autoencoder | latency | 100.000 | pedidos_latency_ms | pedidos_latency_p95_ms | pagos_latency_ms |
| Autoencoder | latency | 300.000 | pedidos_latency_ms | pedidos_latency_p95_ms | pagos_latency_ms |
| Autoencoder | latency | 500.000 | pedidos_latency_ms | pedidos_latency_p95_ms | pagos_latency_ms |
| Isolation Forest | cpu | 0.600 | pedidos_latency_p95_ms | pedidos_latency_ms | pedidos_cpu_cores |
| Isolation Forest | latency | 300.000 | pedidos_latency_p95_ms | pedidos_latency_ms | pagos_cpu_cores |
| Isolation Forest | latency | 500.000 | pedidos_latency_p95_ms | pedidos_latency_ms | pedidos_cpu_cores |
