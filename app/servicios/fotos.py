"""Foto del estudiante, que aparece en su reporte de notas. Una foto por estudiante, en JPG o PNG."""
import os
import uuid

from nucleo.db import get_db


FOTOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'fotos_estudiantes')
TAMANO_MAX_FOTO = 2 * 1024 * 1024  # 2 MB
FIRMAS = {
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'png': [b'\x89PNG\r\n\x1a\n'],
}

ESQUEMA_FOTOS = """
CREATE TABLE IF NOT EXISTS fotos_estudiantes (
    estudiante_id INTEGER PRIMARY KEY REFERENCES estudiantes(id) ON DELETE CASCADE,
    nombre_archivo TEXT NOT NULL,
    subido_en TEXT NOT NULL
)
"""


def asegurar(db):
    db.execute(ESQUEMA_FOTOS)


def tiene_foto(estudiante_id):
    db = get_db()
    asegurar(db)
    return db.execute('SELECT 1 FROM fotos_estudiantes WHERE estudiante_id = ?', (estudiante_id,)).fetchone() is not None


def ruta_foto(estudiante_id):
    """Ruta del archivo de la foto, o None si el estudiante no tiene foto."""
    db = get_db()
    asegurar(db)
    fila = db.execute('SELECT nombre_archivo FROM fotos_estudiantes WHERE estudiante_id = ?',
                      (estudiante_id,)).fetchone()
    if fila is None:
        return None
    ruta = os.path.join(FOTOS_DIR, fila['nombre_archivo'])
    return ruta if os.path.exists(ruta) else None


def guardar_foto(estudiante_id, archivo):
    """Devuelve (True, mensaje) o (False, error)."""
    if archivo is None or not archivo.filename:
        return False, 'Seleccione una imagen.'
    nombre = archivo.filename.lower()
    extension = nombre.rsplit('.', 1)[-1] if '.' in nombre else ''
    if extension not in FIRMAS:
        return False, 'La foto debe ser JPG o PNG.'
    contenido = archivo.read(TAMANO_MAX_FOTO + 1)
    if len(contenido) > TAMANO_MAX_FOTO:
        return False, 'La foto supera el tamaño máximo de 2 MB.'
    if not any(contenido.startswith(firma) for firma in FIRMAS[extension]):
        return False, 'El archivo no es una imagen JPG o PNG válida.'

    db = get_db()
    asegurar(db)
    anterior = db.execute('SELECT nombre_archivo FROM fotos_estudiantes WHERE estudiante_id = ?',
                          (estudiante_id,)).fetchone()
    os.makedirs(FOTOS_DIR, exist_ok=True)
    nombre_en_disco = f'{uuid.uuid4().hex}.{extension}'
    with open(os.path.join(FOTOS_DIR, nombre_en_disco), 'wb') as salida:
        salida.write(contenido)
    db.execute(
        "INSERT INTO fotos_estudiantes (estudiante_id, nombre_archivo, subido_en) "
        "VALUES (?, ?, to_char(localtimestamp, 'YYYY-MM-DD HH24:MI:SS')) "
        "ON CONFLICT (estudiante_id) DO UPDATE SET nombre_archivo = excluded.nombre_archivo, "
        "subido_en = excluded.subido_en",
        (estudiante_id, nombre_en_disco))
    db.commit()
    if anterior:
        try:
            os.remove(os.path.join(FOTOS_DIR, anterior['nombre_archivo']))
        except OSError:
            pass
    return True, 'Foto actualizada.'
