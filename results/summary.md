# Resultados P1: Isolation Forest vs Autoencoder

- Runs: 24 (cpu: 12, latency: 9, normal: 3); validacion cruzada agrupada por run (K=3).
- Features (24): nginx_cpu_cores, nginx_rps, pedidos_cpu_cores, pedidos_cpu_throttled_ps, pedidos_latency_ms, pedidos_latency_p95_ms, pedidos_rps, pedidos_errors_ps, usuarios_cpu_cores, usuarios_cpu_throttled_ps, usuarios_latency_ms, usuarios_latency_p95_ms, usuarios_rps, pagos_cpu_cores, pagos_latency_ms, pagos_latency_p95_ms, pagos_rps, notificaciones_cpu_cores, notificaciones_cpu_throttled_ps, notificaciones_latency_ms, notificaciones_latency_p95_ms, notificaciones_rps, postgres_cpu_cores, postgres_cpu_throttled_ps
- Umbral: percentil 95 fuera de muestra sobre normales de entrenamiento. Alerta = 2 filas consecutivas.
- Resolucion temporal: 5 s (las tasas usan ventanas de 15 s).

## Metricas por fila
Por severidad: filas de los runs de esa falla. TODAS: todos los runs, incluidos los normales.
| modelo | escenario | severidad | precision | recall | f1 | auc | pr_auc | filas_falla |
|---|---|---|---|---|---|---|---|---|
| Isolation Forest | cpu | 0.200 | 0.000 | 0.000 | 0.000 | 0.992 | 0.967 | 72 |
| Isolation Forest | cpu | 0.400 | 0.000 | 0.000 | 0.000 | 0.998 | 0.998 | 72 |
| Isolation Forest | cpu | 0.500 | 0.143 | 0.014 | 0.025 | 0.861 | 0.706 | 72 |
| Isolation Forest | cpu | 0.600 | 0.950 | 0.264 | 0.413 | 0.973 | 0.911 | 72 |
| Isolation Forest | latency | 100.000 | 0.000 | 0.000 | 0.000 | 0.892 | 0.741 | 72 |
| Isolation Forest | latency | 300.000 | 1.000 | 0.014 | 0.027 | 1.000 | 1.000 | 72 |
| Isolation Forest | latency | 500.000 | 1.000 | 0.028 | 0.054 | 0.993 | 0.982 | 72 |
| Isolation Forest | TODAS |  | 0.319 | 0.046 | 0.080 |  |  | 504 |
| Autoencoder | cpu | 0.200 | 1.000 | 0.014 | 0.027 | 0.992 | 0.968 | 72 |
| Autoencoder | cpu | 0.400 | 1.000 | 0.306 | 0.468 | 1.000 | 1.000 | 72 |
| Autoencoder | cpu | 0.500 | 0.985 | 0.917 | 0.950 | 0.993 | 0.989 | 72 |
| Autoencoder | cpu | 0.600 | 0.959 | 0.972 | 0.966 | 0.983 | 0.934 | 72 |
| Autoencoder | latency | 100.000 | 0.986 | 0.986 | 0.986 | 1.000 | 1.000 | 72 |
| Autoencoder | latency | 300.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 72 |
| Autoencoder | latency | 500.000 | 1.000 | 0.972 | 0.986 | 1.000 | 0.999 | 72 |
| Autoencoder | TODAS |  | 0.765 | 0.738 | 0.752 |  |  | 504 |

## Deteccion por evento (run)
| modelo | escenario | severidad | runs | detectadas | t_deteccion_mediana_s |
|---|---|---|---|---|---|
| Autoencoder | cpu | 0.2 | 3 | 0 |  |
| Autoencoder | cpu | 0.4 | 3 | 2 | 64.9 |
| Autoencoder | cpu | 0.5 | 3 | 3 | 19.9 |
| Autoencoder | cpu | 0.6 | 3 | 3 | 14.9 |
| Autoencoder | latency | 100.0 | 3 | 3 | 9.5 |
| Autoencoder | latency | 300.0 | 3 | 3 | 9.4 |
| Autoencoder | latency | 500.0 | 3 | 3 | 14.4 |
| Isolation Forest | cpu | 0.2 | 3 | 0 |  |
| Isolation Forest | cpu | 0.4 | 3 | 0 |  |
| Isolation Forest | cpu | 0.5 | 3 | 0 |  |
| Isolation Forest | cpu | 0.6 | 3 | 1 | 19.9 |
| Isolation Forest | latency | 100.0 | 3 | 0 |  |
| Isolation Forest | latency | 300.0 | 3 | 0 |  |
| Isolation Forest | latency | 500.0 | 3 | 1 | 104.4 |

## Falsas alarmas
| modelo | falsas_alarmas_por_hora | filas_normales_marcadas_pct_runs_normales |
|---|---|---|
| Isolation Forest | 5.51 | 13.02 |
| Autoencoder | 1.84 | 34.60 |

## Sensibilidad del umbral (cota superior, usa etiquetas de test)
Mejor multiplicador del umbral calibrado por modelo y su rendimiento:
| modelo | multiplicador_umbral | precision | recall | f1 | marcadas_pct_en_runs_normales |
|---|---|---|---|---|---|
| Autoencoder | 1.500 | 0.975 | 0.694 | 0.811 | 1.587 |
| Isolation Forest | 0.700 | 0.600 | 0.960 | 0.738 | 68.254 |

## Explicacion (fraccion de runs detectados; solo filas de falla marcadas por el modelo)
| modelo | escenario | severidad | runs_explicados | servicio_ok | variable_ok_top1 | variable_ok_top3 | share_var1 | share_var2 | share_var3 |
|---|---|---|---|---|---|---|---|---|---|
| Autoencoder | cpu | 0.20 | 1 | 0.00 | 0.00 | 0.00 | 0.35 | 0.30 | 0.06 |
| Autoencoder | cpu | 0.40 | 2 | 1.00 | 1.00 | 1.00 | 0.70 | 0.06 | 0.06 |
| Autoencoder | cpu | 0.50 | 3 | 0.67 | 0.67 | 1.00 | 0.52 | 0.12 | 0.08 |
| Autoencoder | cpu | 0.60 | 3 | 0.67 | 0.33 | 0.67 | 0.76 | 0.06 | 0.03 |
| Autoencoder | latency | 100.00 | 3 | 0.67 | 0.67 | 1.00 | 0.81 | 0.11 | 0.03 |
| Autoencoder | latency | 300.00 | 3 | 1.00 | 1.00 | 1.00 | 0.54 | 0.39 | 0.02 |
| Autoencoder | latency | 500.00 | 3 | 1.00 | 0.67 | 1.00 | 0.68 | 0.25 | 0.01 |
| Isolation Forest | cpu | 0.50 | 1 | 1.00 | 1.00 | 1.00 | 0.70 | 0.09 | 0.07 |
| Isolation Forest | cpu | 0.60 | 1 | 1.00 | 1.00 | 1.00 | 0.61 | 0.12 | 0.11 |
| Isolation Forest | latency | 300.00 | 1 | 1.00 | 1.00 | 1.00 | 0.46 | 0.39 | 0.03 |
| Isolation Forest | latency | 500.00 | 1 | 1.00 | 1.00 | 1.00 | 0.45 | 0.38 | 0.03 |

## Variables mas señaladas
| modelo | escenario | severidad | top1_mas_frecuente | top2 | top3 |
|---|---|---|---|---|---|
| Autoencoder | cpu | 0.200 | usuarios_latency_ms | usuarios_latency_p95_ms | postgres_cpu_cores |
| Autoencoder | cpu | 0.400 | pedidos_cpu_cores | notificaciones_cpu_throttled_ps | pedidos_latency_ms |
| Autoencoder | cpu | 0.500 | notificaciones_cpu_throttled_ps | pedidos_cpu_cores | pedidos_cpu_throttled_ps |
| Autoencoder | cpu | 0.600 | pedidos_cpu_throttled_ps | pedidos_latency_ms | pagos_latency_ms |
| Autoencoder | latency | 100.000 | pedidos_latency_ms | pedidos_latency_p95_ms | pedidos_errors_ps |
| Autoencoder | latency | 300.000 | pedidos_latency_ms | pedidos_latency_p95_ms | postgres_cpu_throttled_ps |
| Autoencoder | latency | 500.000 | pedidos_latency_ms | pedidos_latency_p95_ms | pagos_latency_p95_ms |
| Isolation Forest | cpu | 0.500 | pedidos_cpu_throttled_ps | pedidos_latency_p95_ms | pedidos_cpu_cores |
| Isolation Forest | cpu | 0.600 | pedidos_cpu_throttled_ps | pedidos_latency_p95_ms | pedidos_latency_ms |
| Isolation Forest | latency | 300.000 | pedidos_latency_p95_ms | pedidos_latency_ms | pagos_cpu_cores |
| Isolation Forest | latency | 500.000 | pedidos_latency_p95_ms | pedidos_latency_ms | pedidos_cpu_cores |
