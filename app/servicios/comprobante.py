"""Formulario de inscripción en PDF, con el mismo diseño del formulario en papel y los datos digitados."""
import io
import os

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from servicios import documentos as archivos_documentos


AZUL = colors.HexColor('#1f4e8c')
ANCHO_UTIL = 17.6 * cm  # ancho disponible dentro de los márgenes


def _p(texto, tamano=9, negrita=False, color=colors.black, alinear=0):
    estilo = ParagraphStyle('p', fontName='Helvetica-Bold' if negrita else 'Helvetica', fontSize=tamano,
                            textColor=color, leading=tamano + 3, alignment=alinear)
    return Paragraph(texto, estilo)


def _seccion(titulo):
    t = Table([[_p(titulo, 10, True, AZUL)]], colWidths=[ANCHO_UTIL])
    t.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 1, AZUL),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t


def _fila(*celdas):
    """Una fila del formulario. Cada celda es (etiqueta, valor, ancho_cm[, ancho_etiqueta_cm]).

    El valor va sobre una línea, como en el formulario impreso.
    """
    anchos, contenido, estilos = [], [], [
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]
    for indice, celda in enumerate(celdas):
        etiqueta, valor, ancho = celda[0], celda[1], celda[2]
        ancho_etiqueta = celda[3] if len(celda) > 3 else 3.2
        if not etiqueta:
            ancho_etiqueta = 0.1
        anchos += [ancho_etiqueta * cm, (ancho - ancho_etiqueta) * cm]
        contenido += [_p(etiqueta, 9, True) if etiqueta else '', _p(valor or '', 9.5) if valor else '']
        estilos.append(('LINEBELOW', (2 * indice + 1, 0), (2 * indice + 1, 0), 0.6, colors.black))
    tabla = Table([contenido], colWidths=anchos)
    tabla.setStyle(TableStyle(estilos))
    return tabla


def _casilla(marcada):
    return '[X]' if marcada else '[&nbsp;&nbsp;]'


def _ruta_foto(documentos):
    """La foto solo se incrusta si es JPG o PNG y se puede leer."""
    for doc in documentos:
        if doc['nombre'].startswith('Fotografía') and doc['nombre_archivo']:
            ruta = os.path.join(archivos_documentos.DOCS_DIR, doc['nombre_archivo'])
            if doc['nombre_archivo'].lower().endswith(('.jpg', '.jpeg', '.png')) and os.path.exists(ruta):
                try:
                    with PILImage.open(ruta) as imagen:
                        imagen.verify()
                    return ruta
                except Exception:
                    return None
    return None


def _sigla_documento(tipo):
    if not tipo:
        return ''
    if tipo.startswith('CÉDULA DE CIUDADANÍA'):
        return 'CC'
    if tipo.startswith('TARJETA'):
        return 'TI'
    if tipo.startswith('CÉDULA DE EXTRANJERÍA'):
        return 'CE'
    if tipo == 'PASAPORTE':
        return 'PA'
    return tipo


def generar_comprobante(datos, hermanos, documentos):
    """Devuelve los bytes del PDF del formulario de inscripción.

    datos: fila del aspirante. hermanos: lista de dicts (el formulario impreso no los incluye).
    documentos: lista de dicts con nombre, estado, nombre_archivo y nombre_original.
    """
    historia = []
    ruta_foto = _ruta_foto(documentos)

    apellidos = ' '.join(p for p in (datos['primer_apellido'], datos['segundo_apellido']) if p)
    nombres = ' '.join(p for p in (datos['primer_nombre'], datos['segundo_nombre']) if p)
    sigla = _sigla_documento(datos['tipo_documento'])

    # Encabezado: logo, título y recuadro de la foto
    logo = Table([[_p('<b>PLATAFORMA<br/>INSTITUCIONAL</b>', 10, False, AZUL, 1)]],
                 colWidths=[4.6 * cm], rowHeights=[1.6 * cm])
    logo.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.8, AZUL), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    fecha = datos['creado_en'] or ''
    dia, mes, anio = (fecha[8:10], fecha[5:7], fecha[0:4]) if len(fecha) >= 10 else ('', '', '')
    centro = [
        _p('<b>FORMULARIO DE INSCRIPCIÓN</b>', 13, False, colors.black, 1),
        Spacer(1, 8),
        _p(f'Fecha de inscripción: &nbsp;día <u>&nbsp;&nbsp;{dia}&nbsp;&nbsp;</u> &nbsp;mes '
           f'<u>&nbsp;&nbsp;{mes}&nbsp;&nbsp;</u> &nbsp;año <u>&nbsp;&nbsp;{anio}&nbsp;&nbsp;</u>', 9, False,
           colors.black, 1),
    ]

    if ruta_foto:
        contenido_foto = Image(ruta_foto, width=3 * cm, height=4 * cm)
    else:
        contenido_foto = _p('Foto 3x4', 8, False, colors.grey, 1)
    caja_foto = Table([[contenido_foto]], colWidths=[3.6 * cm], rowHeights=[4.6 * cm])
    caja_foto.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.8, colors.black),
                                   ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    encabezado = Table([[logo, centro, caja_foto]],
                       colWidths=[5 * cm, ANCHO_UTIL - 5 * cm - 3.6 * cm, 3.6 * cm])
    encabezado.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                    ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    historia += [encabezado, Spacer(1, 12)]

    # I. IDENTIFICACIÓN
    historia += [_seccion('I.  IDENTIFICACIÓN'), Spacer(1, 4)]
    historia.append(_fila(('Apellidos:', apellidos, 8.6), ('Nombres:', nombres, 9.0)))
    historia.append(_fila(
        ('Identificación:', f'{_casilla(sigla == "TI")} TI &nbsp;&nbsp; {_casilla(sigla == "CC")} CC &nbsp;&nbsp; '
                            f'{_casilla(sigla == "CE")} CE &nbsp;&nbsp; {_casilla(sigla == "PA")} PA', 8.6, 3.6),
        ('Nº', datos['documento'], 9.0, 0.9)))
    historia.append(_fila(
        ('Sexo:', f'{_casilla(datos["sexo"] == "Masculino")} M &nbsp;&nbsp; {_casilla(datos["sexo"] == "Femenino")} F',
         6.0, 1.5),
        ('Lugar de residencia:', f'{datos["ciudad"] or ""} - {datos["departamento"] or ""} - {datos["pais"] or ""}',
         11.6, 3.6)))
    historia.append(_fila(('Dirección:', datos['direccion'], 12.4), ('Barrio:', '', 5.2, 1.8)))
    historia.append(_fila(('Teléfono:', datos['telefono'], 5.8, 2.2), ('Celular:', datos['celular'], 5.8, 2.2),
                          ('EPS:', '', 6.0, 1.4)))
    historia.append(_fila(('Sistema de vinculación al SGSSS:', '', 17.6, 6.0)))
    historia.append(Spacer(1, 8))

    # II. REFERENCIAS PERSONALES Y FAMILIARES
    historia += [_seccion('II.  REFERENCIAS PERSONALES Y FAMILIARES'), Spacer(1, 4)]
    historia.append(_fila(('1. Nombre:', datos['nombre_padre'], 11.6, 2.4), ('Parentesco:', 'Padre', 6.0, 2.2)))
    historia.append(_fila(('Dirección y teléfono:', datos['telefono_padre'], 17.6, 3.6)))
    historia.append(_fila(('2. Nombre:', datos['nombre_madre'], 11.6, 2.4), ('Parentesco:', 'Madre', 6.0, 2.2)))
    historia.append(_fila(('Dirección y teléfono:', datos['telefono_madre'], 17.6, 3.6)))
    historia.append(Spacer(1, 8))

    # III. DATOS ACADÉMICOS
    historia += [_seccion('III.  DATOS ACADÉMICOS  (Marque con una X la casilla correspondiente)'), Spacer(1, 4)]
    es_bachiller = (datos['grado_anterior'] or '').startswith('11')
    historia.append(_fila(
        ('Bachiller:', f'{_casilla(es_bachiller)} SI &nbsp;&nbsp;&nbsp; {_casilla(not es_bachiller)} NO', 17.6, 2.4)))
    historia.append(_fila(
        ('Si su respuesta es NO, indique el último curso aprobado:',
         '' if es_bachiller else (datos['grado_anterior'] or ''), 17.6, 9.6)))
    historia.append(_fila(('Colegio anterior:', datos['colegio_anterior'], 11.6, 3.2),
                          ('Año de finalización:', datos['anio_anterior'], 6.0, 3.6)))
    historia.append(_fila(
        ('Si su respuesta es SI, marque la modalidad:',
         f'{_casilla(False)} Académico &nbsp;&nbsp; {_casilla(False)} Técnico &nbsp;&nbsp; {_casilla(False)} Otro',
         17.6, 9.6)))
    historia.append(_fila(('Puntaje ICFES:', '', 17.6, 3.2)))
    historia.append(Spacer(1, 16))

    historia.append(_p(f'Documentos adjuntos: {len(documentos)}. Este formulario resume los datos digitados en la '
                       'inscripción. La revisión de los documentos la realiza la institución.', 8, False,
                       colors.grey))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=letter, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                      topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                      title='Formulario de inscripción').build(historia)
    return buffer.getvalue()
