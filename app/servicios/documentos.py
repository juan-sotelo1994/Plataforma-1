"""Documentos que suben los aspirantes para cada requisito (PDF o imagen JPG/PNG)."""
import os
import uuid

from werkzeug.utils import secure_filename

from nucleo.db import get_db


# Fuera de static/: no se pueden abrir por una URL pública
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'documentos_aspirantes')
TAMANO_MAX_DOC = 5 * 1024 * 1024  # 5 MB

# Extensiones permitidas por tipo de requisito y la firma inicial del contenido
FORMATOS = {
    'pdf': {
        'extensiones': {'pdf': [b'%PDF-']},
        'etiqueta': 'PDF',
    },
    'imagen': {
        'extensiones': {
            'pdf': [b'%PDF-'],
            'jpg': [b'\xff\xd8\xff'],
            'jpeg': [b'\xff\xd8\xff'],
            'png': [b'\x89PNG\r\n\x1a\n'],
        },
        'etiqueta': 'PDF, JPG o PNG',
    },
}


def guardar_documento(aspirante_id, requisito_id, archivo):
    """Guarda el archivo del requisito y lo deja pendiente de revisión.

    Devuelve (True, mensaje) si se guardó, o (False, mensaje_de_error) si no.
    """
    if archivo is None or not archivo.filename:
        return False, 'Seleccione un archivo.'

    db = get_db()
    requisito = db.execute('SELECT formatos FROM requisitos WHERE id = ?', (requisito_id,)).fetchone()
    if requisito is None:
        return False, 'El requisito no existe.'
    formato = FORMATOS[requisito['formatos']]

    nombre = secure_filename(archivo.filename)
    extension = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''
    if extension not in formato['extensiones']:
        return False, f'Este requisito solo acepta archivos {formato["etiqueta"]}.'

    contenido = archivo.read(TAMANO_MAX_DOC + 1)
    if len(contenido) > TAMANO_MAX_DOC:
        return False, 'El archivo supera el tamaño máximo de 5 MB.'
    if not any(contenido.startswith(firma) for firma in formato['extensiones'][extension]):
        return False, f'El archivo no es un {formato["etiqueta"]} válido.'

    os.makedirs(DOCS_DIR, exist_ok=True)
    nombre_en_disco = f'{uuid.uuid4().hex}.{extension}'
    with open(os.path.join(DOCS_DIR, nombre_en_disco), 'wb') as salida:
        salida.write(contenido)

    anterior = db.execute(
        'SELECT nombre_archivo FROM documentos_aspirante WHERE aspirante_id = ? AND requisito_id = ?',
        (aspirante_id, requisito_id)).fetchone()
    # Al subir de nuevo, el documento vuelve a quedar pendiente de revisión
    db.execute(
        "INSERT INTO documentos_aspirante (aspirante_id, requisito_id, nombre_original, nombre_archivo, subido_en) "
        "VALUES (?, ?, ?, ?, to_char(localtimestamp, 'YYYY-MM-DD HH24:MI:SS')) "
        "ON CONFLICT (aspirante_id, requisito_id) DO UPDATE SET "
        "nombre_original = excluded.nombre_original, nombre_archivo = excluded.nombre_archivo, "
        "subido_en = excluded.subido_en, estado = 'pendiente', observacion = NULL",
        (aspirante_id, requisito_id, nombre, nombre_en_disco))
    db.commit()

    if anterior:
        try:
            os.remove(os.path.join(DOCS_DIR, anterior['nombre_archivo']))
        except OSError:
            pass

    return True, 'Archivo subido. Quedará pendiente de revisión.'
