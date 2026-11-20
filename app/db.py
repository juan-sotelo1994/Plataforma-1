"""Base de datos SQLite (módulo sqlite3 de Python, sin dependencias extra).

El archivo se crea solo en app/instance/plataforma.db al iniciar la app.
"""
import os
import sqlite3

from flask import g


RUTA_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'plataforma.db')

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
    especialidad TEXT
);

CREATE TABLE IF NOT EXISTS materias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    creditos INTEGER NOT NULL DEFAULT 0
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
    jornada_id INTEGER REFERENCES jornadas(id)
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
        conexion.commit()
