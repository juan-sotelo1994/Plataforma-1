"""Hojas de vida de los docentes (.pdf o .doc), compartidas por el panel del docente y el de administración."""
import os
import uuid

from werkzeug.utils import secure_filename

from nucleo.db import get_db


# Se guardan fuera de static/, para que no se puedan abrir por una URL pública
HOJAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'hojas_de_vida')
TAMANO_MAX_HOJA = 5 * 1024 * 1024  # 5 MB
# Extensión permitida y firma inicial del archivo (se revisa el contenido, no solo el nombre)
FIRMAS_HOJA = {
    'pdf': b'%PDF-',
    'doc': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',
}


def guardar_hoja(docente_id, archivo):
    """Guarda la hoja de vida y reemplaza la anterior.

    Devuelve (True, mensaje) si se guardó, o (False, mensaje_de_error) si no.
    """
    if archivo is None or not archivo.filename:
        return False, 'Seleccione un archivo .pdf o .doc.'

    nombre = secure_filename(archivo.filename)
    extension = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''
    if extension not in FIRMAS_HOJA:
        return False, 'Solo se aceptan archivos .pdf o .doc.'

    contenido = archivo.read(TAMANO_MAX_HOJA + 1)
    if len(contenido) > TAMANO_MAX_HOJA:
        return False, 'El archivo supera el tamaño máximo de 5 MB.'
    if not contenido.startswith(FIRMAS_HOJA[extension]):
        return False, 'El contenido del archivo no corresponde a un .pdf o .doc válido.'

    db = get_db()
    os.makedirs(HOJAS_DIR, exist_ok=True)
    nombre_en_disco = f'{uuid.uuid4().hex}.{extension}'
    with open(os.path.join(HOJAS_DIR, nombre_en_disco), 'wb') as salida:
        salida.write(contenido)

    anterior = db.execute(
        'SELECT nombre_archivo FROM hojas_de_vida WHERE docente_id = ?', (docente_id,)).fetchone()
    db.execute(
        "INSERT INTO hojas_de_vida (docente_id, nombre_original, nombre_archivo, subido_en) "
        "VALUES (?, ?, ?, to_char(localtimestamp, 'YYYY-MM-DD HH24:MI:SS')) "
        "ON CONFLICT (docente_id) DO UPDATE SET nombre_original = excluded.nombre_original, "
        "nombre_archivo = excluded.nombre_archivo, subido_en = excluded.subido_en",
        (docente_id, nombre, nombre_en_disco))
    db.commit()

    # Quita el archivo anterior para no dejar archivos huérfanos
    if anterior:
        try:
            os.remove(os.path.join(HOJAS_DIR, anterior['nombre_archivo']))
        except OSError:
            pass

    return True, 'Hoja de vida guardada correctamente.'
