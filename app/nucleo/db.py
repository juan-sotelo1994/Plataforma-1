"""Base de datos SQLite (módulo sqlite3 de Python, sin dependencias extra).

El archivo se crea solo en app/instance/plataforma.db al iniciar la app.
"""
import os
import sqlite3

from flask import g


RUTA_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance', 'plataforma.db')

ESQUEMA = """
CREATE TABLE IF NOT EXISTS jornadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    horario TEXT
);

CREATE TABLE IF NOT EXISTS docentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombres TEXT NOT NULL,
    apellidos TEXT NOT NULL,
    documento TEXT NOT NULL UNIQUE,
    correo TEXT,
    especialidad TEXT,
    sexo TEXT, telefono TEXT, celular TEXT, direccion TEXT,
    pais TEXT, departamento TEXT, ciudad TEXT
);

CREATE TABLE IF NOT EXISTS materias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    creditos INTEGER NOT NULL DEFAULT 0,
    ciclo INTEGER NOT NULL DEFAULT 1 CHECK (ciclo BETWEEN 1 AND 10),
    jornada_id INTEGER REFERENCES jornadas(id)
);

-- Un curso es una materia dictada en una jornada, con un docente, un grupo y un periodo
CREATE TABLE IF NOT EXISTS cursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    materia_id INTEGER NOT NULL REFERENCES materias(id),
    docente_id INTEGER NOT NULL REFERENCES docentes(id),
    jornada_id INTEGER NOT NULL REFERENCES jornadas(id),
    periodo TEXT NOT NULL,
    grupo TEXT NOT NULL,
    cupo INTEGER NOT NULL DEFAULT 0,
    horario TEXT,
    UNIQUE (materia_id, periodo, grupo)
);

CREATE TABLE IF NOT EXISTS estudiantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombres TEXT NOT NULL,
    apellidos TEXT NOT NULL,
    documento TEXT NOT NULL UNIQUE,
    correo TEXT,
    programa TEXT,
    jornada_id INTEGER REFERENCES jornadas(id),
    telefono TEXT, celular TEXT, direccion TEXT, pais TEXT, departamento TEXT, ciudad TEXT,
    nombre_padre TEXT, documento_padre TEXT, telefono_padre TEXT,
    nombre_madre TEXT, documento_madre TEXT, telefono_madre TEXT
);

-- Nota de un estudiante en un curso (escala de 0.0 a 5.0)
CREATE TABLE IF NOT EXISTS calificaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    curso_id INTEGER NOT NULL REFERENCES cursos(id),
    estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
    nota REAL NOT NULL CHECK (nota >= 0 AND nota <= 5),
    UNIQUE (curso_id, estudiante_id)
);

-- Cuentas de docentes y estudiantes (el administrador vive en el .env)
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correo TEXT NOT NULL UNIQUE,
    contrasena_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('docente', 'estudiante')),
    docente_id INTEGER REFERENCES docentes(id) ON DELETE CASCADE,
    estudiante_id INTEGER REFERENCES estudiantes(id) ON DELETE CASCADE
);

-- Inscripción de un estudiante en un curso
CREATE TABLE IF NOT EXISTS matriculas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    curso_id INTEGER NOT NULL REFERENCES cursos(id),
    estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
    UNIQUE (curso_id, estudiante_id)
);

-- Aspirantes que se inscriben desde la página pública (la cuenta vive en la misma fila)
CREATE TABLE IF NOT EXISTS aspirantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombres TEXT NOT NULL,
    apellidos TEXT NOT NULL,
    documento TEXT NOT NULL UNIQUE,
    correo TEXT NOT NULL UNIQUE,
    telefono TEXT,
    nombre_padre TEXT,
    nombre_madre TEXT,
    telefono_padre TEXT,
    telefono_madre TEXT,
    documento_padre TEXT,
    documento_madre TEXT,
    tipo_documento TEXT,
    sexo TEXT,
    primer_nombre TEXT,
    segundo_nombre TEXT,
    primer_apellido TEXT,
    segundo_apellido TEXT,
    direccion TEXT,
    celular TEXT,
    ciudad TEXT,
    pais TEXT,
    departamento TEXT,
    numero_hermanos INTEGER,
    colegio_anterior TEXT,
    grado_anterior TEXT,
    anio_anterior TEXT,
    estudiante_id INTEGER,
    programa TEXT NOT NULL,
    jornada_id INTEGER REFERENCES jornadas(id),
    contrasena_hash TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Marcas internas de la plataforma (por ejemplo, si ya se cargaron los requisitos iniciales)
CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

-- Requisitos que deben cumplir los aspirantes (los crea el administrador)
CREATE TABLE IF NOT EXISTS requisitos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    descripcion TEXT,
    obligatorio INTEGER NOT NULL DEFAULT 1 CHECK (obligatorio IN (0, 1)),
    formatos TEXT NOT NULL DEFAULT 'pdf' CHECK (formatos IN ('pdf', 'imagen')),
    paso INTEGER NOT NULL DEFAULT 1 CHECK (paso IN (1, 2)),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    seccion TEXT NOT NULL DEFAULT 'aspirante'
);

-- Documento que sube un aspirante para cada requisito
CREATE TABLE IF NOT EXISTS documentos_aspirante (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aspirante_id INTEGER NOT NULL REFERENCES aspirantes(id) ON DELETE CASCADE,
    requisito_id INTEGER NOT NULL REFERENCES requisitos(id),
    nombre_original TEXT NOT NULL,
    nombre_archivo TEXT NOT NULL,
    subido_en TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobado', 'rechazado')),
    observacion TEXT,
    UNIQUE (aspirante_id, requisito_id)
);

-- Hermanos del aspirante (se piden en el paso de padres y familia)
CREATE TABLE IF NOT EXISTS hermanos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aspirante_id INTEGER NOT NULL REFERENCES aspirantes(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    edad INTEGER NOT NULL CHECK (edad BETWEEN 0 AND 120),
    parentesco TEXT NOT NULL,
    orden INTEGER NOT NULL DEFAULT 0
);

-- Documentos de formación del docente: título profesional, bachiller, cursos y cartas de experiencia
CREATE TABLE IF NOT EXISTS docentes_documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    docente_id INTEGER NOT NULL REFERENCES docentes(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    nombre_original TEXT NOT NULL,
    nombre_archivo TEXT NOT NULL,
    subido_en TEXT NOT NULL,
    UNIQUE (docente_id, tipo)
);

-- Materias que un docente está habilitado para dictar
CREATE TABLE IF NOT EXISTS docente_materias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    docente_id INTEGER NOT NULL REFERENCES docentes(id) ON DELETE CASCADE,
    materia_id INTEGER NOT NULL REFERENCES materias(id) ON DELETE CASCADE,
    UNIQUE (docente_id, materia_id)
);

-- Hoja de vida del docente: un solo archivo (.pdf o .doc) por docente
CREATE TABLE IF NOT EXISTS hojas_de_vida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    docente_id INTEGER NOT NULL UNIQUE REFERENCES docentes(id) ON DELETE CASCADE,
    nombre_original TEXT NOT NULL,
    nombre_archivo TEXT NOT NULL,
    subido_en TEXT NOT NULL
);

-- Calificación que da un estudiante al docente de un curso (1 a 5)
CREATE TABLE IF NOT EXISTS evaluaciones_docente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    curso_id INTEGER NOT NULL REFERENCES cursos(id),
    estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
    puntuacion INTEGER NOT NULL CHECK (puntuacion BETWEEN 1 AND 5),
    comentario TEXT,
    UNIQUE (curso_id, estudiante_id)
);
"""


def get_db():
    """Conexión de la petición actual (se cierra al terminar)."""
    if 'db' not in g:
        os.makedirs(os.path.dirname(RUTA_DB), exist_ok=True)
        conexion = sqlite3.connect(RUTA_DB)
        conexion.row_factory = sqlite3.Row
        conexion.execute('PRAGMA foreign_keys = ON')
        g.db = conexion
    return g.db


def _cerrar_db(exc=None):
    conexion = g.pop('db', None)
    if conexion is not None:
        conexion.close()


def init_app(app):
    """Registra el cierre de conexiones y crea las tablas si no existen."""
    app.teardown_appcontext(_cerrar_db)
    with app.app_context():
        conexion = get_db()
        conexion.executescript(ESQUEMA)
        _migrar(conexion)
        conexion.commit()


def _migrar(conexion):
    """Agrega columnas nuevas a bases creadas antes de que existieran."""
    columnas_cursos = {fila['name'] for fila in conexion.execute('PRAGMA table_info(cursos)')}
    if 'horario' not in columnas_cursos:
        conexion.execute('ALTER TABLE cursos ADD COLUMN horario TEXT')

    columnas = {fila['name'] for fila in conexion.execute('PRAGMA table_info(materias)')}
    if 'ciclo' not in columnas:
        conexion.execute('ALTER TABLE materias ADD COLUMN ciclo INTEGER NOT NULL DEFAULT 1 '
                         'CHECK (ciclo BETWEEN 1 AND 10)')
    if 'jornada_id' not in columnas:
        conexion.execute('ALTER TABLE materias ADD COLUMN jornada_id INTEGER REFERENCES jornadas(id)')

    columnas = {fila['name'] for fila in conexion.execute('PRAGMA table_info(requisitos)')}
    if 'formatos' not in columnas:
        conexion.execute("ALTER TABLE requisitos ADD COLUMN formatos TEXT NOT NULL DEFAULT 'pdf' "
                         "CHECK (formatos IN ('pdf', 'imagen'))")

    columnas_doc = {fila['name'] for fila in conexion.execute('PRAGMA table_info(docentes)')}
    for columna in ('sexo', 'telefono', 'celular', 'direccion', 'pais', 'departamento', 'ciudad'):
        if columna not in columnas_doc:
            conexion.execute(f'ALTER TABLE docentes ADD COLUMN {columna} TEXT')

    columnas_est = {fila['name'] for fila in conexion.execute('PRAGMA table_info(estudiantes)')}
    for columna in ('telefono', 'celular', 'direccion', 'pais', 'departamento', 'ciudad', 'nombre_padre', 'telefono_padre', 'documento_padre', 'nombre_madre', 'telefono_madre', 'documento_madre'):
        if columna not in columnas_est:
            conexion.execute(f'ALTER TABLE estudiantes ADD COLUMN {columna} TEXT')

    columnas = {fila['name'] for fila in conexion.execute('PRAGMA table_info(aspirantes)')}
    for columna in ('nombre_padre', 'nombre_madre', 'telefono_padre', 'telefono_madre',
                    'documento_padre', 'documento_madre', 'tipo_documento', 'sexo', 'primer_nombre',
                    'segundo_nombre', 'primer_apellido', 'segundo_apellido', 'direccion', 'celular', 'ciudad',
                    'pais', 'departamento', 'numero_hermanos', 'colegio_anterior', 'grado_anterior',
                    'anio_anterior', 'estudiante_id'):
        if columna not in columnas:
            conexion.execute(f'ALTER TABLE aspirantes ADD COLUMN {columna} TEXT')

    columnas = {fila['name'] for fila in conexion.execute('PRAGMA table_info(requisitos)')}
    if 'seccion' not in columnas:
        conexion.execute("ALTER TABLE requisitos ADD COLUMN seccion TEXT NOT NULL DEFAULT 'aspirante'")
    if 'activo' not in columnas:
        conexion.execute('ALTER TABLE requisitos ADD COLUMN activo INTEGER NOT NULL DEFAULT 1 '
                         'CHECK (activo IN (0, 1))')
    if 'paso' not in columnas:
        conexion.execute('ALTER TABLE requisitos ADD COLUMN paso INTEGER NOT NULL DEFAULT 1 '
                         'CHECK (paso IN (1, 2))')
        # Bases existentes: los requisitos de los padres pasan al paso 2
        conexion.execute(f'UPDATE requisitos SET paso = 2 WHERE nombre IN ({", ".join("?" for _ in PASO_2)})',
                         list(PASO_2))

    _sembrar_requisitos(conexion)
    _ajustar_requisitos_aspirante(conexion)
    _ajustar_requisitos_academicos(conexion)
    _ajustar_secciones(conexion)
    _reactivar_sisben(conexion)


# Requisitos de inscripción que pidió el colegio. Se cargan una sola vez; después el
# administrador puede editarlos o eliminarlos sin que vuelvan a aparecer.
REQUISITOS_INICIALES = [
    ('Documento de identidad del aspirante', 'Escaneado del documento de identidad.', 'pdf'),
    ('Fotografía 3x4 con fondo blanco', 'Foto reciente, tamaño 3x4, fondo blanco. Formato JPG o PNG.', 'imagen'),
    ('Notas del colegio anterior', 'Notas del colegio donde estaba matriculado.', 'pdf'),
    ('Paz y salvo del colegio anterior', 'Documento de liberación del colegio o instituto anterior.', 'pdf'),
    ('Certificado de notas', 'Certificado de notas del bachillerato.', 'pdf'),
    ('Recibo de luz escaneado', 'Recibo de servicio público reciente.', 'pdf'),
    ('Documento de identidad del padre', 'Escaneado del documento de identidad del padre.', 'pdf'),
    ('Documento de identidad de la madre', 'Escaneado del documento de identidad de la madre.', 'pdf'),
    ('Afiliación a la EPS', 'Escaneado del documento de afiliación a la EPS.', 'pdf'),
    ('Puntaje del SISBÉN', 'Certificado con el puntaje del SISBÉN.', 'pdf'),
]


# Requisitos que se piden en el paso 2 (padres y familia); los demás son del paso 1 (aspirante)
PASO_2 = (
    'Documento de identidad del padre',
    'Documento de identidad de la madre',
    'Recibo de luz escaneado',
)


# Documentos que el aspirante ya no sube (quedan desactivados, no se borran)
REQUISITOS_DESACTIVADOS = (
    'Notas del colegio anterior',
    'Paz y salvo del colegio anterior',
    'Certificado de notas',
    'Afiliación a la EPS',
    'Puntaje del SISBÉN',
)


def _ajustar_requisitos_aspirante(conexion):
    """Una sola vez: documentos del aspirante según la lista vigente (foto, identidad y carnet de salud)."""
    if conexion.execute("SELECT 1 FROM configuracion WHERE clave = 'requisitos_aspirante_v2'").fetchone():
        return
    conexion.execute(
        'INSERT OR IGNORE INTO requisitos (nombre, descripcion, obligatorio, formatos, paso) '
        "VALUES ('Carnet de salud', 'Escaneado del carnet de salud.', 1, 'pdf', 1)")
    conexion.execute(
        f'UPDATE requisitos SET activo = 0 WHERE nombre IN ({", ".join("?" for _ in REQUISITOS_DESACTIVADOS)})',
        list(REQUISITOS_DESACTIVADOS))
    conexion.execute("INSERT INTO configuracion (clave, valor) VALUES ('requisitos_aspirante_v2', 'si')")


def _ajustar_requisitos_academicos(conexion):
    """Una sola vez: documentos del colegio anterior (notas, certificado, comportamiento y paz y salvo)."""
    if conexion.execute("SELECT 1 FROM configuracion WHERE clave = 'requisitos_academicos_v3'").fetchone():
        return
    conexion.execute("UPDATE requisitos SET nombre = 'Notas del último año cursado', "
                     "descripcion = 'Notas del último año cursado en el colegio anterior.' "
                     "WHERE nombre = 'Notas del colegio anterior'")
    conexion.execute(
        'INSERT OR IGNORE INTO requisitos (nombre, descripcion, obligatorio, formatos, paso) '
        "VALUES ('Acta de comportamiento', 'Acta de comportamiento del colegio anterior.', 1, 'pdf', 1)")
    conexion.execute(
        "UPDATE requisitos SET activo = 1 WHERE nombre IN ('Notas del último año cursado', "
        "'Certificado de notas', 'Paz y salvo del colegio anterior')")
    conexion.execute("INSERT INTO configuracion (clave, valor) VALUES ('requisitos_academicos_v3', 'si')")


def _ajustar_secciones(conexion):
    """Una sola vez: cada requisito queda en la pestaña que le corresponde."""
    if conexion.execute("SELECT 1 FROM configuracion WHERE clave = 'secciones_v4'").fetchone():
        return
    conexion.execute(
        "UPDATE requisitos SET seccion = 'academico' WHERE nombre IN ("
        "'Notas del último año cursado', 'Certificado de notas', 'Acta de comportamiento', "
        "'Paz y salvo del colegio anterior')")
    conexion.execute(
        "UPDATE requisitos SET seccion = 'padres' WHERE nombre IN ("
        "'Documento de identidad del padre', 'Documento de identidad de la madre', 'Recibo de luz escaneado')")
    conexion.execute("INSERT INTO configuracion (clave, valor) VALUES ('secciones_v4', 'si')")


def _reactivar_sisben(conexion):
    """Una sola vez: el puntaje del SISBÉN vuelve a pedirse en la pestaña de documentos."""
    if conexion.execute("SELECT 1 FROM configuracion WHERE clave = 'sisben_v5'").fetchone():
        return
    conexion.execute("UPDATE requisitos SET activo = 1, seccion = 'aspirante' WHERE nombre = 'Puntaje del SISBÉN'")
    conexion.execute("INSERT INTO configuracion (clave, valor) VALUES ('sisben_v5', 'si')")


def _sembrar_requisitos(conexion):
    ya_cargados = conexion.execute(
        "SELECT 1 FROM configuracion WHERE clave = 'requisitos_iniciales'").fetchone()
    if ya_cargados:
        return
    conexion.executemany(
        'INSERT OR IGNORE INTO requisitos (nombre, descripcion, obligatorio, formatos, paso) '
        'VALUES (?, ?, 1, ?, ?)',
        [(nombre, descripcion, formatos, 2 if nombre in PASO_2 else 1)
         for nombre, descripcion, formatos in REQUISITOS_INICIALES])
    conexion.execute("INSERT INTO configuracion (clave, valor) VALUES ('requisitos_iniciales', 'si')")
