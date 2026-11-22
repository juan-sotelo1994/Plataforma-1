"""Base de datos PostgreSQL de la plataforma.

La base se llama "instituto" (DATABASE_URL en app/.env). Cada sede es un esquema de esa base
(sede_1, sede_2, ...) y el esquema "central" guarda las sedes y los administradores de sede.

Conexion da la misma forma de trabajar que sqlite3: los parámetros se escriben con "?", las
filas se leen por nombre o por posición, y cada sentencia que falla no deja rota la transacción.
"""
import os
import re

import psycopg
from flask import g, has_request_context, session
from psycopg import sql


CARPETA = os.path.dirname(os.path.abspath(__file__))
ESQUEMA_SEDE_SQL = os.path.join(CARPETA, 'esquema_sede.sql')
ESQUEMA_CENTRAL_SQL = os.path.join(CARPETA, 'esquema_central.sql')
ESQUEMA_CENTRAL = 'central'
# Sede por defecto (la principal) y plantilla de los requisitos y la configuración de las sedes nuevas
ESQUEMA_PRINCIPAL = 'sede_1'

IntegrityError = psycopg.IntegrityError

# Tablas de cada esquema que tienen columna id (para pedir el id de las filas nuevas)
_TABLAS_CON_ID = {}


class Fila(tuple):
    """Una fila que se lee por posición (fila[0]) o por nombre de columna (fila['nombre'])."""

    def __new__(cls, valores, nombres):
        fila = super().__new__(cls, valores)
        fila._indices = {nombre: indice for indice, nombre in enumerate(nombres)}
        return fila

    def __getitem__(self, clave):
        if isinstance(clave, str):
            return tuple.__getitem__(self, self._indices[clave])
        return tuple.__getitem__(self, clave)

    def keys(self):
        return list(self._indices)


def _fabrica_de_filas(cursor):
    nombres = [columna.name for columna in cursor.description] if cursor.description else []
    return lambda valores: Fila(valores, nombres)


def _url():
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError('Falta DATABASE_URL en app/.env')
    return url


def _traducir(sentencia, tablas_con_id):
    """Adapta una sentencia escrita para SQLite a PostgreSQL. Devuelve (sentencia, si pide el id)."""
    texto = sentencia.replace('?', '%s')
    if re.search(r'INSERT\s+OR\s+IGNORE', texto, re.IGNORECASE):
        texto = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', texto, flags=re.IGNORECASE)
        texto = texto.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
    pide_id = False
    coincidencia = re.match(r'\s*INSERT\s+INTO\s+(\w+)', texto, re.IGNORECASE)
    if coincidencia and coincidencia.group(1) in tablas_con_id and 'RETURNING' not in texto.upper():
        texto = texto.rstrip().rstrip(';') + ' RETURNING id'
        pide_id = True
    return texto, pide_id


class Resultado:
    """Lo que devuelve execute: filas leídas y, en los INSERT, el id de la fila nueva (lastrowid)."""

    def __init__(self, cursor, pide_id):
        self._cursor = cursor
        self.rowcount = cursor.rowcount
        self.lastrowid = None
        if pide_id:
            fila = cursor.fetchone()
            self.lastrowid = fila[0] if fila else None

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor.fetchall())


class Conexion:
    """Conexión a un esquema de la base instituto, con la misma forma de uso que sqlite3."""

    def __init__(self, esquema):
        self.esquema = esquema
        self._pg = psycopg.connect(_url(), row_factory=_fabrica_de_filas)
        self._pg.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(esquema)))
        if esquema not in _TABLAS_CON_ID:
            self.recargar_tablas()

    def recargar_tablas(self):
        """Vuelve a leer qué tablas tienen columna id (después de crear tablas nuevas)."""
        filas = self._pg.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = %s AND column_name = 'id'", (self.esquema,)).fetchall()
        _TABLAS_CON_ID[self.esquema] = {fila[0] for fila in filas}

    def execute(self, sentencia, parametros=()):
        texto, pide_id = _traducir(sentencia, _TABLAS_CON_ID[self.esquema])
        # Cada sentencia va dentro de un punto de guardado: si falla, la transacción sigue sirviendo
        self._pg.execute('SAVEPOINT sentencia')
        cursor = self._pg.cursor()
        try:
            cursor.execute(texto, parametros or None)
        except psycopg.Error:
            self._pg.execute('ROLLBACK TO SAVEPOINT sentencia')
            raise
        resultado = Resultado(cursor, pide_id)
        self._pg.execute('RELEASE SAVEPOINT sentencia')
        return resultado

    def executemany(self, sentencia, lotes):
        texto, _ = _traducir(sentencia, _TABLAS_CON_ID[self.esquema])
        with self._pg.cursor() as cursor:
            cursor.executemany(texto, lotes)

    def executescript(self, script):
        self._pg.execute(script)

    def commit(self):
        self._pg.commit()

    def rollback(self):
        self._pg.rollback()

    def close(self):
        self._pg.close()


def _esquema_activo():
    """El esquema de la sede de la sesión; sin sesión de sede, la sede principal."""
    if has_request_context() and session.get('sede_archivo'):
        return session['sede_archivo']
    return ESQUEMA_PRINCIPAL


def get_db():
    """Conexión de la petición actual (se cierra al terminar). Es la de la sede activa."""
    esquema = _esquema_activo()
    if 'db' in g and g.db_esquema != esquema:
        _cerrar_db()
    if 'db' not in g:
        g.db = Conexion(esquema)
        g.db_esquema = esquema
    return g.db


def _cerrar_db(exc=None):
    conexion = g.pop('db', None)
    g.pop('db_esquema', None)
    if conexion is not None:
        conexion.close()


def crear_base(esquema, plantilla=ESQUEMA_PRINCIPAL):
    """Crea el esquema de una sede nueva con todas sus tablas.

    Copia los requisitos y la configuración de la plantilla (la sede principal), como se hacía
    al crear una base SQLite. Si la plantilla no existe, la sede queda sin requisitos.
    """
    with psycopg.connect(_url()) as pg:
        pg.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(esquema)))
        pg.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(esquema)))
        with open(ESQUEMA_SEDE_SQL, encoding='utf-8') as archivo:
            pg.execute(archivo.read())
        existe_plantilla = pg.execute(
            'SELECT 1 FROM information_schema.schemata WHERE schema_name = %s', (plantilla,)).fetchone()
        if plantilla and existe_plantilla:
            for tabla in ('requisitos', 'configuracion'):
                pg.execute(sql.SQL('INSERT INTO {t} SELECT * FROM {p}.{t}').format(
                    t=sql.Identifier(tabla), p=sql.Identifier(plantilla)))
            pg.execute("SELECT setval(pg_get_serial_sequence('requisitos', 'id'), "
                       "COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM requisitos")
    _TABLAS_CON_ID.pop(esquema, None)


def init_app(app):
    """Registra el cierre de conexiones y prepara el esquema central."""
    from nucleo.sedes import iniciar_central
    app.teardown_appcontext(_cerrar_db)
    iniciar_central()
