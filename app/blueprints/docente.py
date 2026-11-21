from flask import Blueprint, abort, flash, redirect, render_template, request, send_from_directory, session, url_for

from nucleo.db import get_db
from servicios import notas
from servicios.hojas import HOJAS_DIR, guardar_hoja
from nucleo.seguridad import requiere_rol


docente_bp = Blueprint('docente', __name__, url_prefix='/docente')

# Rutas que usa la pantalla de notas (la misma para el docente y el administrador)
RUTAS_NOTAS = {
    'guardar': 'docente.curso',
    'agregar': 'docente.agregar_criterio',
    'eliminar': 'docente.eliminar_criterio',
    'exportar': 'docente.exportar_notas',
}


def _curso_del_docente(curso_id):
    """El curso solo se muestra si le pertenece al docente de la sesión."""
    curso = get_db().execute(
        "SELECT c.id, m.nombre AS materia, m.creditos, c.grupo, c.periodo, c.cupo, j.nombre AS jornada "
        "FROM cursos c "
        "JOIN materias m ON m.id = c.materia_id "
        "JOIN jornadas j ON j.id = c.jornada_id "
        "WHERE c.id = ? AND c.docente_id = ?",
        (curso_id, session['persona_id'])).fetchone()
    if curso is None:
        abort(404)
    return curso


@docente_bp.route('/')
@requiere_rol('docente')
def inicio():
    db = get_db()
    docente = db.execute(
        'SELECT nombres, apellidos, especialidad FROM docentes WHERE id = ?',
        (session['persona_id'],)).fetchone()

    cursos = db.execute(
        "SELECT c.id, m.nombre AS materia, c.grupo, c.periodo, c.cupo, j.nombre AS jornada, "
        "(SELECT COUNT(*) FROM matriculas mt WHERE mt.curso_id = c.id) AS matriculados, "
        "(SELECT COUNT(*) FROM calificaciones k WHERE k.curso_id = c.id) AS calificados, "
        "(SELECT ROUND(AVG(ev.puntuacion), 2) FROM evaluaciones_docente ev WHERE ev.curso_id = c.id) AS evaluacion, "
        "(SELECT COUNT(*) FROM evaluaciones_docente ev WHERE ev.curso_id = c.id) AS evaluaciones "
        "FROM cursos c "
        "JOIN materias m ON m.id = c.materia_id "
        "JOIN jornadas j ON j.id = c.jornada_id "
        "WHERE c.docente_id = ? "
        "ORDER BY j.nombre, c.periodo DESC, m.nombre",
        (session['persona_id'],)).fetchall()

    return render_template('docente/inicio.html', docente=docente, cursos=cursos)


@docente_bp.route('/cursos/<int:curso_id>', methods=['GET', 'POST'])
@requiere_rol('docente')
def curso(curso_id):
    curso = _curso_del_docente(curso_id)

    if request.method == 'POST':
        ok, mensaje = notas.guardar_notas(curso_id, request.form)
        flash(mensaje, 'ok' if ok else 'error')
        return redirect(url_for('docente.curso', curso_id=curso_id))

    criterios, total, estudiantes = notas.estudiantes_con_notas(curso_id)
    evaluacion = get_db().execute(
        "SELECT ROUND(AVG(puntuacion), 2) AS promedio, COUNT(*) AS total "
        "FROM evaluaciones_docente WHERE curso_id = ?",
        (curso_id,)).fetchone()

    return render_template('docente/curso.html', curso=curso, criterios=criterios, total=total,
                           estudiantes=estudiantes, evaluacion=evaluacion, rutas=RUTAS_NOTAS)


@docente_bp.route('/cursos/<int:curso_id>/criterios', methods=['POST'])
@requiere_rol('docente')
def agregar_criterio(curso_id):
    _curso_del_docente(curso_id)
    ok, mensaje = notas.agregar_criterio(curso_id, request.form.get('nombre'), request.form.get('porcentaje'))
    flash(mensaje, 'ok' if ok else 'error')
    return redirect(url_for('docente.curso', curso_id=curso_id))


@docente_bp.route('/cursos/<int:curso_id>/criterios/<int:criterio_id>/eliminar', methods=['POST'])
@requiere_rol('docente')
def eliminar_criterio(curso_id, criterio_id):
    _curso_del_docente(curso_id)
    notas.eliminar_criterio(curso_id, criterio_id)
    flash('Criterio eliminado. Las notas de ese criterio también se borraron.', 'ok')
    return redirect(url_for('docente.curso', curso_id=curso_id))


@docente_bp.route('/cursos/<int:curso_id>/exportar/<formato>')
@requiere_rol('docente')
def exportar_notas(curso_id, formato):
    _curso_del_docente(curso_id)
    return notas.respuesta_exportacion(curso_id, formato)


@docente_bp.route('/materias')
@requiere_rol('docente')
def materias():
    filas = get_db().execute(
        "SELECT m.id, m.codigo, m.nombre, m.creditos, c.id AS id_curso, c.grupo, c.periodo, c.cupo, "
        "j.nombre AS jornada "
        "FROM cursos c "
        "JOIN materias m ON m.id = c.materia_id "
        "JOIN jornadas j ON j.id = c.jornada_id "
        "WHERE c.docente_id = ? "
        "ORDER BY m.nombre, c.periodo DESC, c.grupo",
        (session['persona_id'],)).fetchall()

    # Agrupa los cursos de cada materia que dicta el docente
    materias_dictadas = {}
    for fila in filas:
        materia = materias_dictadas.setdefault(fila['id'], {
            'codigo': fila['codigo'], 'nombre': fila['nombre'],
            'creditos': fila['creditos'], 'cursos': []})
        materia['cursos'].append({
            'id': fila['id_curso'], 'grupo': fila['grupo'], 'periodo': fila['periodo'],
            'cupo': fila['cupo'], 'jornada': fila['jornada']})

    return render_template('docente/materias.html', materias=list(materias_dictadas.values()))


@docente_bp.route('/hoja-de-vida', methods=['GET', 'POST'])
@requiere_rol('docente')
def hoja_de_vida():
    docente_id = session['persona_id']

    if request.method == 'POST':
        ok, mensaje = guardar_hoja(docente_id, request.files.get('archivo'))
        flash(mensaje, 'ok' if ok else 'error')
        return redirect(url_for('docente.hoja_de_vida'))

    hoja = get_db().execute(
        'SELECT nombre_original, subido_en FROM hojas_de_vida WHERE docente_id = ?',
        (docente_id,)).fetchone()
    return render_template('docente/hoja_de_vida.html', hoja=hoja)


@docente_bp.route('/hoja-de-vida/descargar')
@requiere_rol('docente')
def descargar_hoja():
    hoja = get_db().execute(
        'SELECT nombre_original, nombre_archivo FROM hojas_de_vida WHERE docente_id = ?',
        (session['persona_id'],)).fetchone()
    if hoja is None:
        abort(404)
    return send_from_directory(HOJAS_DIR, hoja['nombre_archivo'], as_attachment=True,
                               download_name=hoja['nombre_original'])
