"""Sedes: cada sede tiene su propia base de datos. La base central guarda la lista de sedes
y los administradores de cada sede."""
import os
import sqlite3

INSTANCIA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance')
RUTA_CENTRAL = os.path.join(INSTANCIA, 'central.db')
# La base que ya existía pasa a ser la primera sede
ARCHIVO_SEDE_PRINCIPAL = 'plataforma.db'

ESQUEMA_CENTRAL = """
CREATE TABLE IF NOT EXISTS sedes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    archivo TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS admins_sede (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correo TEXT NOT NULL UNIQUE,
    contrasena_hash TEXT NOT NULL,
    sede_id INTEGER NOT NULL REFERENCES sedes(id) ON DELETE CASCADE
);

-- Contraseña del superadministrador después de cambiarla (si no existe, vale la del .env)
CREATE TABLE IF NOT EXISTS credencial_superadmin (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    contrasena_hash TEXT NOT NULL
);
"""


def conectar(ruta):
    os.makedirs(INSTANCIA, exist_ok=True)
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    conexion.execute('PRAGMA foreign_keys = ON')
    return conexion


def iniciar_central():
    conexion = conectar(RUTA_CENTRAL)
    try:
        conexion.executescript(ESQUEMA_CENTRAL)
        if not conexion.execute('SELECT 1 FROM sedes').fetchone():
            conexion.execute('INSERT INTO sedes (nombre, archivo) VALUES (?, ?)',
                             ('Sede principal', ARCHIVO_SEDE_PRINCIPAL))
        conexion.commit()
    finally:
        conexion.close()


def listar_sedes():
    conexion = conectar(RUTA_CENTRAL)
    try:
        return conexion.execute('SELECT id, nombre, archivo FROM sedes ORDER BY id').fetchall()
    finally:
        conexion.close()


def ruta_sede(archivo):
    return os.path.join(INSTANCIA, archivo)


def correo_en_uso(correo):
    """True si el correo ya tiene cuenta o inscripción en alguna sede, o es de un administrador de sede."""
    correo = correo.strip().lower()
    central = conectar(RUTA_CENTRAL)
    try:
        if central.execute('SELECT 1 FROM admins_sede WHERE correo = ?', (correo,)).fetchone():
            return True
    finally:
        central.close()
    for sede in listar_sedes():
        ruta = ruta_sede(sede['archivo'])
        if not os.path.exists(ruta):
            continue
        conexion = conectar(ruta)
        try:
            if conexion.execute(
                    'SELECT 1 FROM usuarios WHERE correo = ? UNION SELECT 1 FROM aspirantes WHERE correo = ?',
                    (correo, correo)).fetchone():
                return True
        finally:
            conexion.close()
    return False
