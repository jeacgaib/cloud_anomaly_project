CREATE TABLE usuarios (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL,
    email   TEXT UNIQUE NOT NULL
);
CREATE TABLE pedidos (
    id         SERIAL PRIMARY KEY,
    usuario_id INT REFERENCES usuarios(id),
    total      DOUBLE PRECISION NOT NULL,
    creado     TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE pagos (
    id        SERIAL PRIMARY KEY,
    pedido_id INT NOT NULL,
    monto     DOUBLE PRECISION NOT NULL,
    estado    TEXT NOT NULL,
    creado    TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE notificaciones (
    id         SERIAL PRIMARY KEY,
    pedido_id  INT NOT NULL,
    usuario_id INT NOT NULL,
    canal      TEXT NOT NULL,
    creado     TIMESTAMPTZ DEFAULT now()
);
INSERT INTO usuarios (nombre, email)
SELECT 'usuario_' || g, 'usuario_' || g || '@demo.com' FROM generate_series(1, 100) g;
