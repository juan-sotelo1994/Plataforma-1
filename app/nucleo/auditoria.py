"""Auditoría de cada sede: quién hizo qué y cuándo.

Cada sede guarda su propio registro en su base. La tabla se crea sola la primera vez,
así las bases que ya existían también la reciben.
"""
import datetime

from flask import has_request_context, session

ESQUEMA_AUDITORIA = """
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    usuario TEXT NOT NULL,
    accion TEXT NOT NULL,
    detalle TEXT
)
"""


def asegurar(conexion):
    conexion.execute(ESQUEMA_AUDITORIA)


def _usuario_actual():
    if has_request_context() and session.get('usuario'):
        return session['usuario']
    return 'sistema'


def registrar(db, accion, detalle='', usuario=None):
    """Anota una acción en la base de la sede. Se guarda junto con la operación, al hacer commit."""
    asegurar(db)
    db.execute(
        'INSERT INTO auditoria (fecha, usuario, accion, detalle) VALUES (?, ?, ?, ?)',
        (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), usuario or _usuario_actual(), accion, detalle))
