"""Sedes: cada sede es un esquema de la base instituto. El esquema "central" guarda la lista de
sedes, los administradores de cada sede y la contraseña del superadministrador (si la cambió).

En la columna "archivo" de la tabla sedes se guarda el nombre del esquema de la sede (por ejemplo
sede_1). Se conserva ese nombre para no cambiar el resto de la aplicación.
"""
import uuid

import psycopg
from psycopg import sql

from nucleo.db import (ESQUEMA_CENTRAL, ESQUEMA_CENTRAL_SQL, ESQUEMA_PRINCIPAL, Conexion, crear_base)


def conectar_central():
    return Conexion(ESQUEMA_CENTRAL)


def conectar_sede(esquema):
    return Conexion(esquema)


def nombre_nuevo_esquema():
    return f'sede_{uuid.uuid4().hex[:10]}'


def iniciar_central():
    """Crea el esquema central la primera vez (en una base nueva, con una sede principal)."""
    from nucleo.db import _url
    with psycopg.connect(_url()) as pg:
        existe = pg.execute(
            'SELECT 1 FROM information_schema.schemata WHERE schema_name = %s', (ESQUEMA_CENTRAL,)).fetchone()
        if existe:
            return
        pg.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(ESQUEMA_CENTRAL)))
        pg.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(ESQUEMA_CENTRAL)))
        with open(ESQUEMA_CENTRAL_SQL, encoding='utf-8') as archivo:
            pg.execute(archivo.read())
        pg.execute("INSERT INTO sedes (nombre, archivo) VALUES ('Sede principal', %s)", (ESQUEMA_PRINCIPAL,))
    crear_base(ESQUEMA_PRINCIPAL, plantilla=None)


def listar_sedes():
    conexion = conectar_central()
    try:
        return conexion.execute('SELECT id, nombre, archivo FROM sedes ORDER BY id').fetchall()
    finally:
        conexion.close()


def correo_en_uso(correo):
    """True si el correo ya tiene cuenta o inscripción en alguna sede, o es de un administrador de sede."""
    correo = correo.strip().lower()
    central = conectar_central()
    try:
        if central.execute('SELECT 1 FROM admins_sede WHERE correo = ?', (correo,)).fetchone():
            return True
    finally:
        central.close()
    for sede in listar_sedes():
        conexion = conectar_sede(sede['archivo'])
        try:
            if conexion.execute(
                    'SELECT 1 FROM usuarios WHERE correo = ? UNION SELECT 1 FROM aspirantes WHERE correo = ?',
                    (correo, correo)).fetchone():
                return True
        finally:
            conexion.close()
    return False
