from flask import Blueprint, abort, flash, redirect, render_template, request, send_from_directory, session, url_for

from db import get_db
from hojas import HOJAS_DIR, guardar_hoja
from seguridad import requiere_rol


docente_bp = Blueprint('docente', __name__, url_prefix='/docente')


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
        return _guardar_notas(curso_id)

    db = get_db()
    estudiantes = db.execute(
        "SELECT e.id, e.codigo, e.apellidos || ' ' || e.nombres AS nombre, k.nota "
        "FROM matriculas mt "
        "JOIN estudiantes e ON e.id = mt.estudiante_id "
        "LEFT JOIN calificaciones k ON k.curso_id = mt.curso_id AND k.estudiante_id = e.id "
        "WHERE mt.curso_id = ? "
        "ORDER BY e.apellidos, e.nombres",
        (curso_id,)).fetchall()

    evaluacion = db.execute(
        "SELECT ROUND(AVG(puntuacion), 2) AS promedio, COUNT(*) AS total "
        "FROM evaluaciones_docente WHERE curso_id = ?",
        (curso_id,)).fetchone()

    return render_template('docente/curso.html', curso=curso, estudiantes=estudiantes,
                           evaluacion=evaluacion)


def _guardar_notas(curso_id):
    """Guarda las notas escritas. Un campo vacío deja la nota como estaba.

    Si alguna nota no es válida, no se guarda ninguna, para no dejar el curso a medias.
    """
    db = get_db()
    matriculados = [fila['estudiante_id'] for fila in db.execute(
        'SELECT estudiante_id FROM matriculas WHERE curso_id = ?', (curso_id,)).fetchall()]
    # Solo los estudiantes matriculados pueden tener nota en este curso

    notas = []
    for estudiante_id in matriculados:
        bruto = request.form.get(f'nota_{estudiante_id}', '').strip().replace(',', '.')
        if not bruto:
            continue
        try:
            valor = float(bruto)
        except ValueError:
            flash('Hay notas que no son números. No se guardó ninguna. Revise y vuelva a intentar.', 'error')
            return redirect(url_for('docente.curso', curso_id=curso_id))
        if not 0 <= valor <= 5:
            flash('Las notas deben estar entre 0.0 y 5.0. No se guardó ninguna.', 'error')
            return redirect(url_for('docente.curso', curso_id=curso_id))
        notas.append((estudiante_id, valor))

    for estudiante_id, valor in notas:
        db.execute(
            'INSERT INTO calificaciones (curso_id, estudiante_id, nota) VALUES (?, ?, ?) '
            'ON CONFLICT (curso_id, estudiante_id) DO UPDATE SET nota = excluded.nota',
            (curso_id, estudiante_id, valor))
    db.commit()

    if notas:
        flash(f'Se guardaron {len(notas)} nota(s).', 'ok')
    else:
        flash('No escribió ninguna nota nueva.', 'error')
    return redirect(url_for('docente.curso', curso_id=curso_id))


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
