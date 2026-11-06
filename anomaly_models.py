"""Modelos compartidos: Scaler, Isolation Forest (baseline) y Autoencoder (primera IA).

Usado por evaluate.py (validacion cruzada), train_final.py (entrenamiento y guardado) y detect.py (inferencia).
Mantener las clases aqui evita que los modelos guardados dependan de otros scripts.
"""
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor

META = {"timestamp", "label", "rps_target", "severity", "run_ok", "fault_start"}
PCT = 0.95
SEED = 0
COMPONENTS = ["nginx", "pedidos", "usuarios", "pagos", "notificaciones", "postgres"]


class Scaler:
    """Estandarizacion con suelo de desviacion (5 % de la media) y recorte a ±30 desviaciones."""

    def fit(self, X):
        self.mu = X.mean(0)
        sd = X.std(0)
        self.sd = np.maximum.reduce([sd, 0.05 * np.abs(self.mu), np.full_like(sd, 1e-6)])
        return self

    def transform(self, X):
        return np.clip((X - self.mu) / self.sd, -30, 30)


class IFModel:
    name = "Isolation Forest"

    def fit(self, Z):
        self.m = IsolationForest(n_estimators=300, random_state=SEED).fit(Z)
        return self

    def score(self, Z):
        return -self.m.score_samples(Z)

    def dev(self, Z):          # desviacion por variable (sustituto de atribucion: IF no trae una propia)
        return np.abs(Z)


class AEModel:
    name = "Autoencoder"

    def fit(self, Z):
        from sklearn.neural_network import MLPRegressor  # noqa: F811
        self.ms = [MLPRegressor(hidden_layer_sizes=(16, 6, 16), activation="tanh", alpha=1e-3,
                                max_iter=800, tol=1e-6, random_state=SEED + i).fit(Z, Z)
                   for i in range(3)]
        return self

    def _rec(self, Z):
        return np.mean([m.predict(Z) for m in self.ms], axis=0)

    def dev(self, Z):          # error de reconstruccion por variable
        return (Z - self._rec(Z)) ** 2

    def score(self, Z):
        return self.dev(Z).mean(1)


MODELS = [IFModel, AEModel]


def feature_columns(d):
    """Features usadas por los modelos: numericas, sin RAM absoluta (deriva entre runs), sin
    nginx_conn_active (= numero de hilos de JMeter) y sin columnas constantes."""
    num = [c for c in d.select_dtypes(include="number").columns if c not in META]
    feat = [c for c in num if not c.endswith("ram_mb") and c != "nginx_conn_active"]
    return [c for c in feat if d[c].nunique() > 1]
