from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from nucleo.db import get_db
from servicios.geografia import DEPARTAMENTOS
from nucleo.seguridad import requiere_rol


# Panel del estudiante. Los datos salen de la base de datos según la sesión.
# El nombre del blueprint ("dashboard") es el que usan las plantillas.
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/panel')

# Notas desde este valor se consideran aprobadas (escala de 0.0 a 5.0)
NOTA_APROBATORIA = 3.0

# Enlaces de recursos: reemplazar por las direcciones reales de la institución
BIBLIOTECA_URL = '#'
MOODLE_URL = '#'

MENU_GRUPOS = [
    {'titulo': 'Mi cuenta', 'enlaces': [
        {'texto': 'Actualizar mis datos', 'url': '/panel/datos'},
    ]},
    {'titulo': 'Académico', 'enlaces': [
        {'texto': 'Notas (PDF)', 'url': '#'},
        {'texto': 'Notas', 'url': '#'},
        {'texto': 'Estatuto estudiantil', 'url': '#'},
    ]},
    {'titulo': 'Trámites', 'enlaces': [
        {'texto': 'Autorizaciones', 'url': '#'},
        {'texto': 'Acuerdos de pago', 'url': '#'},
        {'texto': 'Recibos', 'url': '#'},
        {'texto': 'Constancias en línea', 'url': '#'},
    ]},
    {'titulo': 'Recursos', 'enlaces': [
        {'texto': 'Biblioteca virtual', 'url': BIBLIOTECA_URL},
        {'texto': 'Aula virtual (Moodle)', 'url': MOODLE_URL},
    ]},
]

PESTANAS = ['Resumen', 'Notas', 'Matrícula', 'Pagos', 'Constancias', 'Encuesta']


def _datos_estudiante(estudiante_id):
    return get_db().execute(
        "SELECT e.id, e.codigo, e.nombres, e.apellidos, e.documento, e.correo, e.programa, "
        "j.nombre AS jornada "
        "FROM estudiantes e LEFT JOIN jornadas j ON j.id = e.jornada_id "
        "WHERE e.id = ?", (estudiante_id,)).fetchone()


def _cursos_del_estudiante(estudiante_id):
    return get_db().execute(
        "SELECT c.id AS curso_id, m.nombre AS materia, m.creditos, c.grupo, c.periodo, c.horario, "
        "COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente, j.nombre AS jornada, "
        "k.nota AS nota, ev.puntuacion AS evaluacion "
        "FROM matriculas mt "
        "JOIN cursos c ON c.id = mt.curso_id "
        "JOIN materias m ON m.id = c.materia_id "
        "LEFT JOIN docentes d ON d.id = c.docente_id "
        "JOIN jornadas j ON j.id = c.jornada_id "
        "LEFT JOIN calificaciones k ON k.curso_id = c.id AND k.estudiante_id = mt.estudiante_id "
        "LEFT JOIN evaluaciones_docente ev ON ev.curso_id = c.id AND ev.estudiante_id = mt.estudiante_id "
        "WHERE mt.estudiante_id = ? "
        "ORDER BY c.periodo DESC, m.nombre", (estudiante_id,)).fetchall()


@dashboard_bp.route('/')
@requiere_rol('estudiante')
def dash_view():
    estudiante_id = session['persona_id']
    estudiante = _datos_estudiante(estudiante_id)
    if estudiante is None:
        flash('No se encontró su información de estudiante.', 'error')
        return redirect(url_for('autenticar.logout'))

    cursos = _cursos_del_estudiante(estudiante_id)
    notas = [curso['nota'] for curso in cursos if curso['nota'] is not None]
    promedio = round(sum(notas) / len(notas), 2) if notas else None

    return render_template('panel/inicio.html', usuario=estudiante, cursos=cursos,
                           promedio=promedio, calificados=len(notas),
                           nota_aprobatoria=NOTA_APROBATORIA,
                           grupos=MENU_GRUPOS, pestanas=PESTANAS,
                           importante=[], observaciones=[])


@dashboard_bp.route('/evaluar/<int:curso_id>', methods=['POST'])
@requiere_rol('estudiante')
def evaluar(curso_id):
    estudiante_id = session['persona_id']
    db = get_db()

    matriculado = db.execute(
        'SELECT 1 FROM matriculas WHERE curso_id = ? AND estudiante_id = ?',
        (curso_id, estudiante_id)).fetchone()
    if not matriculado:
        flash('Solo puede calificar a los docentes de los cursos en los que está matriculado.', 'error')
        return redirect(url_for('dashboard.dash_view'))

    ya_evaluado = db.execute(
        'SELECT 1 FROM evaluaciones_docente WHERE curso_id = ? AND estudiante_id = ?',
        (curso_id, estudiante_id)).fetchone()
    if ya_evaluado:
        flash('Ya calificó al docente de este curso.', 'error')
        return redirect(url_for('dashboard.dash_view'))

    try:
        puntuacion = int(request.form.get('puntuacion', ''))
    except ValueError:
        puntuacion = 0
    if not 1 <= puntuacion <= 5:
        flash('Seleccione una calificación de 1 a 5.', 'error')
        return redirect(url_for('dashboard.dash_view'))

    comentario = request.form.get('comentario', '').strip()[:500] or None
    db.execute(
        'INSERT INTO evaluaciones_docente (curso_id, estudiante_id, puntuacion, comentario) '
        'VALUES (?, ?, ?, ?)',
        (curso_id, estudiante_id, puntuacion, comentario))
    db.commit()
    flash('Gracias. Su calificación al docente fue registrada.', 'ok')
    return redirect(url_for('dashboard.dash_view'))


CAMPOS_DATOS_ESTUDIANTE = ['nombres', 'apellidos', 'celular', 'telefono', 'pais', 'departamento', 'ciudad',
                           'direccion', 'nombre_padre', 'documento_padre', 'telefono_padre',
                           'nombre_madre', 'documento_madre', 'telefono_madre']
OBLIGATORIOS_DATOS_ESTUDIANTE = {
    'nombres': 'Nombres', 'apellidos': 'Apellidos', 'celular': 'Celular', 'direccion': 'Dirección',
    'ciudad': 'Municipio', 'nombre_padre': 'Nombre del padre', 'telefono_padre': 'Contacto del padre',
    'nombre_madre': 'Nombre de la madre', 'telefono_madre': 'Contacto de la madre',
}


@dashboard_bp.route('/datos', methods=['GET', 'POST'])
@requiere_rol('estudiante')
def datos():
    db = get_db()
    estudiante_id = session['persona_id']

    if request.method == 'POST':
        valores = {c: request.form.get(c, '').strip()[:120] for c in CAMPOS_DATOS_ESTUDIANTE}
        faltan = [etiqueta for c, etiqueta in OBLIGATORIOS_DATOS_ESTUDIANTE.items() if not valores[c]]
        if faltan:
            flash('Complete: ' + ', '.join(faltan) + '.', 'error')
            return redirect(url_for('dashboard.datos'))
        db.execute('UPDATE estudiantes SET ' + ', '.join(f'{c} = ?' for c in valores) + ' WHERE id = ?',
                   [valores[c] for c in valores] + [estudiante_id])
        db.commit()
        flash('Sus datos fueron actualizados.', 'ok')
        return redirect(url_for('dashboard.datos'))

    estudiante = db.execute('SELECT * FROM estudiantes WHERE id = ?', (estudiante_id,)).fetchone()
    return render_template('panel/datos.html', estudiante=estudiante, usuario=estudiante,
                           grupos=MENU_GRUPOS, departamentos=DEPARTAMENTOS,
                           obligatorios=OBLIGATORIOS_DATOS_ESTUDIANTE)
