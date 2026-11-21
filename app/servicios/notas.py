"""Notas por criterio de un curso: criterios, definitiva y exportación.

Lo usan el portal del docente y el del administrador, así que las reglas viven aquí.
"""
import csv
import io

from flask import abort, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.utils import secure_filename

from nucleo.db import get_db


def info_curso(curso_id):
    return get_db().execute(
        "SELECT c.id, c.docente_id, m.nombre AS materia, m.creditos, c.grupo, c.periodo, c.cupo, c.horario, "
        "j.nombre AS jornada, COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente "
        "FROM cursos c "
        "JOIN materias m ON m.id = c.materia_id "
        "JOIN jornadas j ON j.id = c.jornada_id "
        "LEFT JOIN docentes d ON d.id = c.docente_id "
        "WHERE c.id = ?", (curso_id,)).fetchone()


def criterios(curso_id):
    return get_db().execute(
        'SELECT id, nombre, porcentaje FROM criterios_evaluacion WHERE curso_id = ? ORDER BY orden, id',
        (curso_id,)).fetchall()


def definitiva(lista_criterios, notas):
    """Promedio ponderado por porcentaje. Solo existe si los porcentajes suman 100 % y hay todas las notas."""
    if not lista_criterios or abs(sum(c['porcentaje'] for c in lista_criterios) - 100) > 0.01:
        return None
    if any(c['id'] not in notas for c in lista_criterios):
        return None
    return round(sum(notas[c['id']] * c['porcentaje'] for c in lista_criterios) / 100, 2)


def estudiantes_con_notas(curso_id):
    """Criterios, porcentaje total y estudiantes matriculados con sus notas y su definitiva."""
    db = get_db()
    lista_criterios = criterios(curso_id)
    total = sum(c['porcentaje'] for c in lista_criterios)

    notas_por_estudiante = {}
    for fila in db.execute(
            "SELECT np.criterio_id, np.estudiante_id, np.nota FROM notas_criterio np "
            "JOIN criterios_evaluacion c ON c.id = np.criterio_id WHERE c.curso_id = ?",
            (curso_id,)).fetchall():
        notas_por_estudiante.setdefault(fila['estudiante_id'], {})[fila['criterio_id']] = fila['nota']

    estudiantes = []
    for fila in db.execute(
            "SELECT e.id, e.codigo, e.documento, e.nombres, e.apellidos, "
            "e.apellidos || ' ' || e.nombres AS nombre "
            "FROM matriculas mt JOIN estudiantes e ON e.id = mt.estudiante_id "
            "WHERE mt.curso_id = ? ORDER BY e.apellidos, e.nombres",
            (curso_id,)).fetchall():
        notas = notas_por_estudiante.get(fila['id'], {})
        estudiantes.append({'id': fila['id'], 'codigo': fila['codigo'], 'documento': fila['documento'],
                            'nombres': fila['nombres'], 'apellidos': fila['apellidos'], 'nombre': fila['nombre'],
                            'notas': notas, 'definitiva': definitiva(lista_criterios, notas)})
    return lista_criterios, total, estudiantes


def recalcular_definitivas(curso_id):
    """Ajusta la nota definitiva de cada estudiante según los criterios y notas actuales."""
    db = get_db()
    lista_criterios = criterios(curso_id)
    for matricula in db.execute('SELECT estudiante_id FROM matriculas WHERE curso_id = ?', (curso_id,)).fetchall():
        estudiante_id = matricula['estudiante_id']
        notas = {fila['criterio_id']: fila['nota'] for fila in db.execute(
            "SELECT np.criterio_id, np.nota FROM notas_criterio np "
            "JOIN criterios_evaluacion c ON c.id = np.criterio_id "
            "WHERE c.curso_id = ? AND np.estudiante_id = ?", (curso_id, estudiante_id)).fetchall()}
        valor = definitiva(lista_criterios, notas)
        if valor is None:
            db.execute('DELETE FROM calificaciones WHERE curso_id = ? AND estudiante_id = ?',
                       (curso_id, estudiante_id))
        else:
            db.execute(
                'INSERT INTO calificaciones (curso_id, estudiante_id, nota) VALUES (?, ?, ?) '
                'ON CONFLICT (curso_id, estudiante_id) DO UPDATE SET nota = excluded.nota',
                (curso_id, estudiante_id, valor))


def agregar_criterio(curso_id, nombre, bruto_porcentaje):
    """Devuelve (ok, mensaje). Guarda el criterio si el porcentaje cabe en 100 %."""
    db = get_db()
    nombre = (nombre or '').strip()
    try:
        porcentaje = float(str(bruto_porcentaje or '').strip().replace(',', '.'))
    except ValueError:
        porcentaje = 0
    total = sum(c['porcentaje'] for c in criterios(curso_id))

    if not nombre:
        return False, 'Escriba el nombre del criterio, por ejemplo Parcial.'
    if not 0 < porcentaje <= 100:
        return False, 'El porcentaje debe estar entre 0 y 100.'
    if total + porcentaje > 100 + 0.01:
        return False, (f'Con {porcentaje:g} % los criterios pasarían de 100 %. '
                       f'Actualmente suman {total:g} %.')
    orden = db.execute('SELECT COALESCE(MAX(orden), 0) + 1 FROM criterios_evaluacion WHERE curso_id = ?',
                       (curso_id,)).fetchone()[0]
    db.execute('INSERT INTO criterios_evaluacion (curso_id, nombre, porcentaje, orden) VALUES (?, ?, ?, ?)',
               (curso_id, nombre, porcentaje, orden))
    db.commit()
    return True, 'Criterio agregado.'


def eliminar_criterio(curso_id, criterio_id):
    db = get_db()
    db.execute('DELETE FROM criterios_evaluacion WHERE id = ? AND curso_id = ?', (criterio_id, curso_id))
    recalcular_definitivas(curso_id)
    db.commit()


def guardar_notas(curso_id, formulario):
    """Devuelve (ok, mensaje). Un campo vacío borra esa nota; si una nota no es válida no se guarda ninguna."""
    db = get_db()
    lista_criterios = criterios(curso_id)
    if not lista_criterios:
        return False, 'Primero cree los criterios de evaluación del curso.'

    matriculados = [fila['estudiante_id'] for fila in db.execute(
        'SELECT estudiante_id FROM matriculas WHERE curso_id = ?', (curso_id,)).fetchall()]

    cambios = []
    for criterio in lista_criterios:
        for estudiante_id in matriculados:
            bruto = formulario.get(f'nota_{criterio["id"]}_{estudiante_id}', '').strip().replace(',', '.')
            if not bruto:
                cambios.append((criterio['id'], estudiante_id, None))
                continue
            try:
                valor = float(bruto)
            except ValueError:
                return False, 'Hay notas que no son números. No se guardó ninguna. Revise y vuelva a intentar.'
            if not 0 <= valor <= 5:
                return False, 'Las notas deben estar entre 0.0 y 5.0. No se guardó ninguna.'
            cambios.append((criterio['id'], estudiante_id, valor))

    for criterio_id, estudiante_id, valor in cambios:
        if valor is None:
            db.execute('DELETE FROM notas_criterio WHERE criterio_id = ? AND estudiante_id = ?',
                       (criterio_id, estudiante_id))
        else:
            db.execute(
                'INSERT INTO notas_criterio (criterio_id, estudiante_id, nota) VALUES (?, ?, ?) '
                'ON CONFLICT (criterio_id, estudiante_id) DO UPDATE SET nota = excluded.nota',
                (criterio_id, estudiante_id, valor))
    recalcular_definitivas(curso_id)
    db.commit()
    registradas = sum(1 for c in cambios if c[2] is not None)
    return True, f'Notas guardadas. Se registraron {registradas} calificación(es) parcial(es).'


def _tabla(lista_criterios, estudiantes):
    encabezado = ['Código', 'Documento', 'Apellidos', 'Nombres'] + [c['nombre'] for c in lista_criterios] + ['Definitiva']
    filas = []
    for estudiante in estudiantes:
        notas = [f"{estudiante['notas'][c['id']]:.1f}" if c['id'] in estudiante['notas'] else ''
                 for c in lista_criterios]
        valor = f"{estudiante['definitiva']:.2f}" if estudiante['definitiva'] is not None else ''
        filas.append([estudiante['codigo'], estudiante['documento'], estudiante['apellidos'],
                      estudiante['nombres'], *notas, valor])
    return encabezado, filas


def nombre_archivo(curso, extension):
    base = secure_filename(f"notas_{curso['materia']}_{curso['grupo']}_{curso['periodo']}") or 'notas'
    return f'{base}.{extension}'


def exportar_csv(curso, lista_criterios, estudiantes):
    encabezado, filas = _tabla(lista_criterios, estudiantes)
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(encabezado)
    escritor.writerows(filas)
    # BOM para que Excel abra bien las tildes
    return ('﻿' + salida.getvalue()).encode('utf-8')


def respuesta_exportacion(curso_id, formato):
    """Descarga las notas del curso en CSV o PDF."""
    if formato not in ('csv', 'pdf'):
        abort(404)
    curso = info_curso(curso_id)
    if curso is None:
        abort(404)
    lista_criterios, _, estudiantes = estudiantes_con_notas(curso_id)
    if formato == 'csv':
        return send_file(io.BytesIO(exportar_csv(curso, lista_criterios, estudiantes)), mimetype='text/csv',
                         as_attachment=True, download_name=nombre_archivo(curso, 'csv'))
    return send_file(io.BytesIO(exportar_pdf(curso, lista_criterios, estudiantes)), mimetype='application/pdf',
                     as_attachment=True, download_name=nombre_archivo(curso, 'pdf'))


def exportar_pdf(curso, lista_criterios, estudiantes):
    encabezado, filas = _tabla(lista_criterios, estudiantes)
    buffer = io.BytesIO()
    documento = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                                  leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                                  topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph(f"<b>Notas: {curso['materia']} · grupo {curso['grupo']}</b>", estilos['Title']),
        Paragraph(f"Periodo {curso['periodo']} · Jornada {curso['jornada']} · Docente {curso['docente']}",
                  estilos['Normal']),
        Spacer(1, 0.5 * cm),
    ]
    tabla = Table([encabezado, *filas], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('ALIGN', (4, 1), (-1, -1), 'CENTER'),
    ]))
    elementos.append(tabla)
    documento.build(elementos)
    return buffer.getvalue()
