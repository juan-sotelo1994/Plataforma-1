"""Documentos de formación del docente (solo PDF)."""
import os
import uuid

from werkzeug.utils import secure_filename

from nucleo.db import get_db


# Carpeta fuera de static/: no se puede abrir por una URL pública
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'docentes')
TAMANO_MAX = 5 * 1024 * 1024  # 5 MB
FIRMA_PDF = b'%PDF-'

# tipo: (etiqueta, obligatorio)
TIPOS = {
    'titulo_profesional': ('Título profesional', True),
    'titulo_bachiller': ('Título de bachiller', True),
    'cursos_realizados': ('Últimos cursos realizados', True),
    'cartas_experiencia': ('Cartas de experiencia', False),
}


# Certificados de antecedentes: tipo: (etiqueta, enlace oficial para descargarlo, obligatorio)
ANTECEDENTES = {
    'pasado_judicial': ('Pasado judicial', 'https://antecedentes.policia.gov.co:7005/WebJudicial/', True),
    'antecedentes_policia': ('Certificado de antecedentes en la Policía',
                             'https://antecedentes.policia.gov.co:7005/WebJudicial/', True),
    'antecedentes_fiscales': ('Certificado de antecedentes fiscales',
                              'https://www.contraloria.gov.co/control-fiscal/responsabilidad-fiscal/certificado-de-antecedentes-fiscales', True),
    'redam': ('Certificado del REDAM', 'https://redam.justicia.gov.co/', True),
    'delitos_sexuales': ('Certificado de delitos sexuales', 'https://inhabilidades.policia.gov.co:8080/', True),
}


def listar(docente_id):
    filas = get_db().execute('SELECT tipo, nombre_original, subido_en FROM docentes_documentos WHERE docente_id = ?',
                             (docente_id,)).fetchall()
    return {fila['tipo']: dict(fila) for fila in filas}


def guardar(docente_id, tipo, archivo):
    """Guarda el PDF del tipo indicado y reemplaza el anterior. Devuelve (ok, mensaje)."""
    if tipo not in TIPOS and tipo not in ANTECEDENTES:
        return False, 'Tipo de documento no válido.'
    if archivo is None or not archivo.filename:
        return False, 'Seleccione un archivo PDF.'
    nombre = secure_filename(archivo.filename)
    if not nombre.lower().endswith('.pdf'):
        return False, 'Solo se aceptan archivos .pdf.'
    contenido = archivo.read(TAMANO_MAX + 1)
    if len(contenido) > TAMANO_MAX:
        return False, 'El archivo supera el tamaño máximo de 5 MB.'
    if not contenido.startswith(FIRMA_PDF):
        return False, 'El archivo no es un PDF válido.'

    db = get_db()
    os.makedirs(DOCS_DIR, exist_ok=True)
    nombre_en_disco = f'{uuid.uuid4().hex}.pdf'
    with open(os.path.join(DOCS_DIR, nombre_en_disco), 'wb') as salida:
        salida.write(contenido)

    anterior = db.execute('SELECT nombre_archivo FROM docentes_documentos WHERE docente_id = ? AND tipo = ?',
                          (docente_id, tipo)).fetchone()
    db.execute(
        "INSERT INTO docentes_documentos (docente_id, tipo, nombre_original, nombre_archivo, subido_en) "
        "VALUES (?, ?, ?, ?, datetime('now', 'localtime')) "
        "ON CONFLICT (docente_id, tipo) DO UPDATE SET nombre_original = excluded.nombre_original, "
        "nombre_archivo = excluded.nombre_archivo, subido_en = excluded.subido_en",
        (docente_id, tipo, nombre, nombre_en_disco))
    db.commit()
    if anterior:
        try:
            os.remove(os.path.join(DOCS_DIR, anterior['nombre_archivo']))
        except OSError:
            pass
    etiqueta = TIPOS[tipo][0] if tipo in TIPOS else ANTECEDENTES[tipo][0]
    return True, f'{etiqueta} guardado.'
