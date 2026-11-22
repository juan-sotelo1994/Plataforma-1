"""Reporte de calificaciones del estudiante en PDF: su foto, sus materias por periodo con el porcentaje
y la nota de cada estrategia, la definitiva, la observación del docente y el promedio de cada periodo."""
import io
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from blueprints.web import EMPRESA
from servicios import fotos, notas

AZUL = colors.HexColor('#1e3a8a')
GRIS = colors.HexColor('#e2e8f0')

# Materias del estudiante con su definitiva y su observación del docente
SQL_MATERIAS = """
SELECT c.id AS curso_id, c.periodo, m.codigo, m.nombre AS materia, k.nota,
       o.texto AS observacion,
       (SELECT COUNT(*) FROM matriculas mt2 JOIN cursos c2 ON c2.id = mt2.curso_id
        WHERE mt2.estudiante_id = mt.estudiante_id AND c2.materia_id = m.id) AS veces
FROM matriculas mt
JOIN cursos c ON c.id = mt.curso_id
JOIN materias m ON m.id = c.materia_id
LEFT JOIN calificaciones k ON k.curso_id = c.id AND k.estudiante_id = mt.estudiante_id
LEFT JOIN observaciones_notas o ON o.curso_id = c.id AND o.estudiante_id = mt.estudiante_id
WHERE mt.estudiante_id = ?
ORDER BY c.periodo, m.nombre
"""

SQL_CRITERIOS = """
SELECT cr.nombre, cr.porcentaje, k.nota
FROM criterios_evaluacion cr
LEFT JOIN notas_criterio k ON k.criterio_id = cr.id AND k.estudiante_id = ?
WHERE cr.curso_id = ?
ORDER BY cr.orden, cr.id
"""


def _promedio(notas_lista):
    valores = [n for n in notas_lista if n is not None]
    return round(sum(valores) / len(valores), 2) if valores else None


def _desglose(db, estudiante_id, curso_id, observacion):
    """Texto de la celda: cada estrategia con su porcentaje, su nota y su aporte, y la observación."""
    lineas = []
    for criterio in db.execute(SQL_CRITERIOS, (estudiante_id, curso_id)).fetchall():
        etiqueta = f'{escape(criterio["nombre"])} ({criterio["porcentaje"]:g} %)'
        if criterio['nota'] is None:
            lineas.append(f'{etiqueta}: Pendiente')
        else:
            aporte = criterio['nota'] * criterio['porcentaje'] / 100
            lineas.append(f'{etiqueta}: {criterio["nota"]:.1f} → aporta {aporte:.2f}')
    if not lineas:
        lineas.append('Sin criterios de evaluación')
    if observacion:
        lineas.append(f'<i>Observación del docente: {escape(observacion)}</i>')
    return '<br/>'.join(lineas)


def _celda_foto(estudiante, celda):
    ruta = fotos.ruta_foto(estudiante['id'])
    if ruta:
        return Image(ruta, width=2.8 * cm, height=3.4 * cm, kind='proportional')
    return Paragraph('Sin foto', celda)


def generar(db, estudiante, sede_nombre):
    """Devuelve el PDF como un buffer listo para enviar."""
    notas.asegurar_observaciones(db)
    filas = db.execute(SQL_MATERIAS, (estudiante['id'],)).fetchall()
    periodos = {}
    for fila in filas:
        periodos.setdefault(fila['periodo'], []).append(fila)

    estilos = getSampleStyleSheet()
    celda = ParagraphStyle('celda', parent=estilos['Normal'], fontSize=8, leading=10)
    titulo = ParagraphStyle('titulo', parent=estilos['Title'], fontSize=15, alignment=0, textColor=AZUL)
    periodo_estilo = ParagraphStyle('periodo', parent=estilos['Normal'], fontSize=9, alignment=1,
                                    fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4)

    historia = [
        Paragraph('REPORTE DE CALIFICACIONES', titulo),
        Paragraph(f'{escape(EMPRESA["nombre"])} · {escape(sede_nombre or "")}', celda),
        Spacer(1, 10),
    ]

    datos = [
        ['Nombres', estudiante['nombres'], 'Documento', estudiante['documento']],
        ['Apellidos', estudiante['apellidos'], 'Código', estudiante['codigo']],
        ['Programa', estudiante['programa'] or '—', 'Jornada', estudiante['jornada'] or '—'],
    ]
    tabla_datos = Table([[Paragraph(escape(str(c)), celda) for c in fila] for fila in datos],
                        colWidths=[2.4 * cm, 5.2 * cm, 2.4 * cm, 4.4 * cm])
    tabla_datos.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, AZUL),
        ('BACKGROUND', (0, 0), (0, -1), GRIS),
        ('BACKGROUND', (2, 0), (2, -1), GRIS),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    encabezado = Table([[tabla_datos, _celda_foto(estudiante, celda)]], colWidths=[14.4 * cm, 4.0 * cm])
    encabezado.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
    ]))
    historia += [encabezado, Spacer(1, 8)]

    todas = []
    for periodo in sorted(periodos):
        historia.append(Paragraph(f'PERIODO ACADÉMICO {escape(periodo)}', periodo_estilo))
        definitivas = []
        cuerpo = [['Código', 'Materia', 'Porcentajes y notas', 'Definitiva',
                   Paragraph('<b>Veces cursada</b>', celda)]]
        for fila in periodos[periodo]:
            definitivas.append(fila['nota'])
            cuerpo.append([
                fila['codigo'],
                Paragraph(escape(fila['materia']), celda),
                Paragraph(_desglose(db, estudiante['id'], fila['curso_id'], fila['observacion']), celda),
                f'{fila["nota"]:.2f}' if fila['nota'] is not None else 'Pendiente',
                str(fila['veces']),
            ])
        todas += definitivas
        promedio = _promedio(definitivas)
        cuerpo.append([Paragraph('<b>PROMEDIO PARCIAL</b>', celda), '', '',
                       f'{promedio:.2f}' if promedio is not None else '—', ''])
        tabla = Table(cuerpo, colWidths=[2.0 * cm, 4.4 * cm, 7.8 * cm, 2.0 * cm, 2.2 * cm], repeatRows=1)
        tabla.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 0), (-1, 0), GRIS),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#94a3b8')),
            ('ALIGN', (3, 0), (4, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('SPAN', (0, -1), (2, -1)),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8fafc')),
        ]))
        historia += [tabla]

    general = _promedio(todas)
    historia += [Spacer(1, 14),
                 Paragraph('<b>Promedio general acumulado:</b> '
                           + (f'{general:.2f}' if general is not None else 'Pendiente'), celda)]
    if not periodos:
        historia.append(Paragraph('Todavía no tiene materias registradas.', celda))

    salida = io.BytesIO()
    documento = SimpleDocTemplate(salida, pagesize=letter, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                                  topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                                  title='Reporte de calificaciones', author=EMPRESA['nombre'])
    documento.build(historia)
    salida.seek(0)
    return salida
