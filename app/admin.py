import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from db import get_db
from hojas import guardar_hoja
from seguridad import requiere_rol


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# Configuración de cada entidad del panel. Las consultas y las tablas son internas
# (no vienen del usuario), así que pueden armarse con el nombre de la tabla.
ENTIDADES = {
    'jornadas': {
        'titulo': 'Jornadas',
        'singular': 'jornada',
        'tabla': 'jornadas',
        'consulta': 'SELECT id, nombre, horario FROM jornadas ORDER BY nombre',
        'columnas': [('Nombre', 'nombre'), ('Horario', 'horario')],
        'campos': [
            {'nombre': 'nombre', 'etiqueta': 'Nombre', 'requerido': True,
             'ejemplo': 'Mañana'},
            {'nombre': 'horario', 'etiqueta': 'Horario', 'ejemplo': '6:00 a. m. – 12:00 m.'},
        ],
    },
    'docentes': {
        'titulo': 'Docentes',
        'singular': 'docente',
        'tabla': 'docentes',
        'consulta': ("SELECT d.id, d.nombres, d.apellidos, d.documento, d.correo, d.especialidad, "
                     "(SELECT GROUP_CONCAT(m.nombre, ', ') FROM docente_materias dm "
                     " JOIN materias m ON m.id = dm.materia_id WHERE dm.docente_id = d.id) AS materias, "
                     "(SELECT h.nombre_original FROM hojas_de_vida h WHERE h.docente_id = d.id) AS hoja "
                     "FROM docentes d ORDER BY d.apellidos, d.nombres"),
        'columnas': [('Nombres', 'nombres'), ('Apellidos', 'apellidos'),
                     ('Documento', 'documento'), ('Correo', 'correo'),
                     ('Materias que puede dictar', 'materias'), ('Hoja de vida', 'hoja')],
        'campos': [
            {'nombre': 'nombres', 'etiqueta': 'Nombres', 'requerido': True},
            {'nombre': 'apellidos', 'etiqueta': 'Apellidos', 'requerido': True},
            {'nombre': 'documento', 'etiqueta': 'Documento', 'requerido': True},
            {'nombre': 'correo', 'etiqueta': 'Correo', 'tipo': 'email'},
            {'nombre': 'especialidad', 'etiqueta': 'Especialidad'},
        ],
    },
    'materias': {
        'titulo': 'Materias',
        'singular': 'materia',
        'tabla': 'materias',
        'consulta': 'SELECT id, codigo, nombre, creditos FROM materias ORDER BY nombre',
        'columnas': [('Código', 'codigo'), ('Nombre', 'nombre'), ('Créditos', 'creditos')],
        'campos': [
            {'nombre': 'codigo', 'etiqueta': 'Código', 'requerido': True, 'ejemplo': 'SIS-101'},
            {'nombre': 'nombre', 'etiqueta': 'Nombre', 'requerido': True},
            {'nombre': 'creditos', 'etiqueta': 'Créditos', 'tipo': 'number', 'ejemplo': '3'},
        ],
    },
    'cursos': {
        'titulo': 'Cursos',
        'singular': 'curso',
        'tabla': 'cursos',
        'consulta': ("SELECT c.id, m.nombre AS materia, c.grupo, c.periodo, "
                     "d.nombres || ' ' || d.apellidos AS docente, j.nombre AS jornada, c.cupo "
                     "FROM cursos c "
                     "JOIN materias m ON m.id = c.materia_id "
                     "JOIN docentes d ON d.id = c.docente_id "
                     "JOIN jornadas j ON j.id = c.jornada_id "
                     "ORDER BY c.periodo DESC, m.nombre, c.grupo"),
        'columnas': [('Materia', 'materia'), ('Grupo', 'grupo'), ('Periodo', 'periodo'),
                     ('Docente', 'docente'), ('Jornada', 'jornada'), ('Cupo', 'cupo')],
        'campos': [
            {'nombre': 'materia_id', 'etiqueta': 'Materia', 'tipo': 'select', 'requerido': True,
             'opciones_sql': 'SELECT id, nombre || \' (\' || codigo || \')\' AS texto FROM materias ORDER BY nombre'},
            {'nombre': 'docente_id', 'etiqueta': 'Docente', 'tipo': 'select', 'requerido': True,
             'opciones_sql': ("SELECT id, nombres || ' ' || apellidos AS texto "
                              "FROM docentes ORDER BY apellidos, nombres")},
            {'nombre': 'jornada_id', 'etiqueta': 'Jornada', 'tipo': 'select', 'requerido': True,
             'opciones_sql': 'SELECT id, nombre AS texto FROM jornadas ORDER BY nombre'},
            {'nombre': 'periodo', 'etiqueta': 'Periodo', 'requerido': True, 'ejemplo': '2026-B'},
            {'nombre': 'grupo', 'etiqueta': 'Grupo', 'requerido': True, 'ejemplo': '01'},
            {'nombre': 'cupo', 'etiqueta': 'Cupo', 'tipo': 'number', 'ejemplo': '30'},
        ],
    },
    'estudiantes': {
        'titulo': 'Estudiantes',
        'singular': 'estudiante',
        'tabla': 'estudiantes',
        'consulta': ("SELECT e.id, e.codigo, e.nombres || ' ' || e.apellidos AS nombre, "
                     "e.documento, e.correo, e.programa, j.nombre AS jornada "
                     "FROM estudiantes e LEFT JOIN jornadas j ON j.id = e.jornada_id "
                     "ORDER BY e.apellidos, e.nombres"),
        'columnas': [('Código', 'codigo'), ('Nombre', 'nombre'), ('Documento', 'documento'),
                     ('Programa', 'programa'), ('Jornada', 'jornada')],
        'campos': [
            {'nombre': 'codigo', 'etiqueta': 'Código', 'requerido': True},
            {'nombre': 'nombres', 'etiqueta': 'Nombres', 'requerido': True},
            {'nombre': 'apellidos', 'etiqueta': 'Apellidos', 'requerido': True},
            {'nombre': 'documento', 'etiqueta': 'Documento', 'requerido': True},
            {'nombre': 'correo', 'etiqueta': 'Correo', 'tipo': 'email'},
            {'nombre': 'programa', 'etiqueta': 'Programa'},
            {'nombre': 'jornada_id', 'etiqueta': 'Jornada', 'tipo': 'select',
             'opciones_sql': 'SELECT id, nombre AS texto FROM jornadas ORDER BY nombre'},
        ],
    },
    'calificaciones': {
        'titulo': 'Calificaciones',
        'singular': 'calificación',
        'tabla': 'calificaciones',
        'consulta': ("SELECT k.id, m.nombre AS materia, c.grupo, c.periodo, "
                     "e.nombres || ' ' || e.apellidos AS estudiante, k.nota "
                     "FROM calificaciones k "
                     "JOIN cursos c ON c.id = k.curso_id "
                     "JOIN materias m ON m.id = c.materia_id "
                     "JOIN estudiantes e ON e.id = k.estudiante_id "
                     "ORDER BY c.periodo DESC, m.nombre, e.apellidos"),
        'columnas': [('Materia', 'materia'), ('Grupo', 'grupo'), ('Periodo', 'periodo'),
                     ('Estudiante', 'estudiante'), ('Nota', 'nota')],
        'campos': [
            {'nombre': 'curso_id', 'etiqueta': 'Curso', 'tipo': 'select', 'requerido': True,
             'opciones_sql': ("SELECT c.id, m.nombre || ' · grupo ' || c.grupo || ' (' || c.periodo || ')' AS texto "
                              "FROM cursos c JOIN materias m ON m.id = c.materia_id "
                              "ORDER BY c.periodo DESC, m.nombre")},
            {'nombre': 'estudiante_id', 'etiqueta': 'Estudiante', 'tipo': 'select', 'requerido': True,
             'opciones_sql': ("SELECT id, apellidos || ' ' || nombres AS texto "
                              "FROM estudiantes ORDER BY apellidos, nombres")},
            {'nombre': 'nota', 'etiqueta': 'Nota (0.0 a 5.0)', 'tipo': 'decimal', 'requerido': True,
             'minimo': 0, 'maximo': 5, 'ejemplo': '4.2'},
        ],
    },
    'matriculas': {
        'titulo': 'Matrículas',
        'singular': 'matrícula',
        'tabla': 'matriculas',
        'consulta': ("SELECT mt.id, e.codigo, e.apellidos || ' ' || e.nombres AS estudiante, "
                     "m.nombre AS materia, c.grupo, c.periodo, "
                     "d.nombres || ' ' || d.apellidos AS docente "
                     "FROM matriculas mt "
                     "JOIN estudiantes e ON e.id = mt.estudiante_id "
                     "JOIN cursos c ON c.id = mt.curso_id "
                     "JOIN materias m ON m.id = c.materia_id "
                     "JOIN docentes d ON d.id = c.docente_id "
                     "ORDER BY c.periodo DESC, m.nombre, e.apellidos"),
        'columnas': [('Código', 'codigo'), ('Estudiante', 'estudiante'), ('Materia', 'materia'),
                     ('Grupo', 'grupo'), ('Periodo', 'periodo'), ('Docente', 'docente')],
        'campos': [
            {'nombre': 'curso_id', 'etiqueta': 'Curso', 'tipo': 'select', 'requerido': True,
             'opciones_sql': ("SELECT c.id, m.nombre || ' · grupo ' || c.grupo || ' (' || c.periodo || ')' AS texto "
                              "FROM cursos c JOIN materias m ON m.id = c.materia_id "
                              "ORDER BY c.periodo DESC, m.nombre")},
            {'nombre': 'estudiante_id', 'etiqueta': 'Estudiante', 'tipo': 'select', 'requerido': True,
             'opciones_sql': ("SELECT id, apellidos || ' ' || nombres AS texto "
                              "FROM estudiantes ORDER BY apellidos, nombres")},
        ],
    },
}

# Tipos de persona que pueden tener una cuenta: (tabla, etiqueta)
ROLES_CUENTA = {
    'docente': ('docentes', 'Docente'),
    'estudiante': ('estudiantes', 'Estudiante'),
}


# Ranking de cursos por promedio de notas. Solo cuentan los cursos con al menos una nota.
CONSULTA_RANKING = """
SELECT c.id, m.nombre AS materia, c.grupo, c.periodo,
       d.nombres || ' ' || d.apellidos AS docente,
       AVG(k.nota) AS promedio, COUNT(k.id) AS evaluados
FROM calificaciones k
JOIN cursos c ON c.id = k.curso_id
JOIN materias m ON m.id = c.materia_id
JOIN docentes d ON d.id = c.docente_id
GROUP BY c.id
ORDER BY promedio DESC, m.nombre
"""


def ranking_cursos():
    """Devuelve (ranking, mejores, peores). Los mejores y peores pueden ser varios si hay empate."""
    ranking = get_db().execute(CONSULTA_RANKING).fetchall()
    if not ranking:
        return ranking, [], []
    maximo = ranking[0]['promedio']
    minimo = ranking[-1]['promedio']
    mejores = [fila for fila in ranking if fila['promedio'] == maximo]
    peores = [fila for fila in ranking if fila['promedio'] == minimo]
    return ranking, mejores, peores


requiere_admin = requiere_rol('admin')

# Al quitar una matrícula también se quita la calificación de ese estudiante en ese curso
SQL_LIMPIAR_CALIFICACION = """
DELETE FROM calificaciones
WHERE curso_id = (SELECT curso_id FROM matriculas WHERE id = ?)
  AND estudiante_id = (SELECT estudiante_id FROM matriculas WHERE id = ?)
"""


def _config(entidad):
    config = ENTIDADES.get(entidad)
    if config is None:
        abort(404)
    return config


def _opciones(campo):
    """Opciones de un campo select: lista de (id, texto)."""
    filas = get_db().execute(campo['opciones_sql']).fetchall()
    return [(fila['id'], fila['texto']) for fila in filas]


def _valores_del_formulario(config):
    valores = {}
    for campo in config['campos']:
        bruto = request.form.get(campo['nombre'], '').strip()
        etiqueta = campo['etiqueta']

        if campo.get('requerido') and not bruto:
            raise ValueError(f'El campo {etiqueta} es obligatorio.')

        if campo.get('tipo') == 'number':
            try:
                valores[campo['nombre']] = int(bruto or 0)
            except ValueError:
                raise ValueError(f'{etiqueta} debe ser un número entero.')
        elif campo.get('tipo') == 'decimal':
            try:
                valor = float(bruto.replace(',', '.')) if bruto else None
            except ValueError:
                raise ValueError(f'{etiqueta} debe ser un número.')
            if valor is not None and not campo['minimo'] <= valor <= campo['maximo']:
                raise ValueError(f'{etiqueta} debe estar entre {campo["minimo"]} y {campo["maximo"]}.')
            valores[campo['nombre']] = valor
        elif campo.get('tipo') == 'select':
            valores[campo['nombre']] = int(bruto) if bruto else None
        else:
            valores[campo['nombre']] = bruto or None
    return valores


SQL_MATERIAS_OPCIONES = "SELECT id, nombre || ' (' || codigo || ')' AS texto FROM materias ORDER BY nombre"


def _docente_puede_dictar(docente_id, materia_id):
    fila = get_db().execute(
        'SELECT 1 FROM docente_materias WHERE docente_id = ? AND materia_id = ?',
        (docente_id, materia_id)).fetchone()
    return fila is not None


def _guardar_extras_docente(docente_id):
    """Guarda las materias habilitadas y la hoja de vida que vienen en el formulario de docente."""
    db = get_db()
    for materia in request.form.getlist('materias'):
        if materia.isdigit():
            db.execute('INSERT OR IGNORE INTO docente_materias (docente_id, materia_id) VALUES (?, ?)',
                       (docente_id, int(materia)))
    db.commit()

    archivo = request.files.get('hoja')
    if archivo is not None and archivo.filename:
        ok, mensaje = guardar_hoja(docente_id, archivo)
        if not ok:
            flash(f'El docente se guardó, pero la hoja de vida no: {mensaje}', 'error')


@admin_bp.route('/')
@requiere_admin
def inicio():
    db = get_db()
    conteos = {
        clave: db.execute(f'SELECT COUNT(*) FROM {config["tabla"]}').fetchone()[0]
        for clave, config in ENTIDADES.items()
    }
    ranking, mejores, peores = ranking_cursos()
    return render_template('admin/inicio.html', conteos=conteos, entidades=ENTIDADES,
                           ranking=ranking, mejores=mejores, peores=peores)


@admin_bp.route('/<entidad>', methods=['GET', 'POST'])
@requiere_admin
def entidad(entidad):
    config = _config(entidad)
    db = get_db()

    if request.method == 'POST':
        try:
            valores = _valores_del_formulario(config)
            if entidad == 'cursos' and not _docente_puede_dictar(valores['docente_id'], valores['materia_id']):
                raise ValueError('Ese docente no está habilitado para dictar esa materia. '
                                 'Revise las materias que puede dictar en su registro.')
            columnas = ', '.join(valores)
            marcas = ', '.join('?' for _ in valores)
            cursor = db.execute(f'INSERT INTO {config["tabla"]} ({columnas}) VALUES ({marcas})',
                                list(valores.values()))
            db.commit()
            flash('Registro guardado correctamente.', 'ok')
            if entidad == 'docentes':
                _guardar_extras_docente(cursor.lastrowid)
        except ValueError as error:
            flash(str(error), 'error')
        except sqlite3.IntegrityError:
            flash('No se pudo guardar. Revise que el código, el documento o el grupo no estén '
                  'repetidos y que las relaciones seleccionadas existan.', 'error')
        return redirect(url_for('admin.entidad', entidad=entidad))

    filas = db.execute(config['consulta']).fetchall()
    campos = []
    for campo in config['campos']:
        campo = dict(campo)
        if campo.get('tipo') == 'select':
            campo['opciones'] = _opciones(campo)
        campos.append(campo)

    materias_opciones = _opciones({'opciones_sql': SQL_MATERIAS_OPCIONES}) if entidad == 'docentes' else None
    return render_template('admin/entidad.html', entidad=entidad, config=config,
                           filas=filas, campos=campos, entidades=ENTIDADES,
                           materias_opciones=materias_opciones)


def _materias_del_formulario():
    return [int(m) for m in request.form.getlist('materias') if m.isdigit()]


def _actualizar_extras_docente(docente_id, materias):
    """Reemplaza las materias habilitadas y, si se subió un archivo, la hoja de vida."""
    db = get_db()
    db.execute('DELETE FROM docente_materias WHERE docente_id = ?', (docente_id,))
    for materia_id in materias:
        db.execute('INSERT OR IGNORE INTO docente_materias (docente_id, materia_id) VALUES (?, ?)',
                   (docente_id, materia_id))
    db.commit()

    archivo = request.files.get('hoja')
    if archivo is not None and archivo.filename:
        ok, mensaje = guardar_hoja(docente_id, archivo)
        if not ok:
            flash(f'Los datos se actualizaron, pero la hoja de vida no: {mensaje}', 'error')


@admin_bp.route('/<entidad>/<int:registro_id>/editar', methods=['GET', 'POST'])
@requiere_admin
def editar(entidad, registro_id):
    config = _config(entidad)
    db = get_db()
    registro = db.execute(f'SELECT * FROM {config["tabla"]} WHERE id = ?', (registro_id,)).fetchone()
    if registro is None:
        abort(404)

    if request.method == 'POST':
        try:
            valores = _valores_del_formulario(config)
            materias = _materias_del_formulario() if entidad == 'docentes' else []

            if entidad == 'cursos' and not _docente_puede_dictar(valores['docente_id'], valores['materia_id']):
                raise ValueError('Ese docente no está habilitado para dictar esa materia. '
                                 'Revise las materias que puede dictar en su registro.')
            if entidad == 'docentes':
                # No se puede quitar una materia si el docente ya tiene cursos de esa materia
                consulta_quitadas = ('SELECT DISTINCT m.nombre FROM cursos c '
                                     'JOIN materias m ON m.id = c.materia_id WHERE c.docente_id = ?')
                parametros = [registro_id]
                if materias:
                    consulta_quitadas += ' AND c.materia_id NOT IN (%s)' % ', '.join('?' for _ in materias)
                    parametros += materias
                quitadas = db.execute(consulta_quitadas, parametros).fetchall()
                if quitadas:
                    nombres = ', '.join(fila['nombre'] for fila in quitadas)
                    raise ValueError(f'No puede quitar {nombres}: el docente tiene cursos de esa materia.')

            asignaciones = ', '.join(f'{columna} = ?' for columna in valores)
            db.execute(f'UPDATE {config["tabla"]} SET {asignaciones} WHERE id = ?',
                       [*valores.values(), registro_id])
            db.commit()
            if entidad == 'docentes':
                _actualizar_extras_docente(registro_id, materias)
            flash('Registro actualizado correctamente.', 'ok')
            return redirect(url_for('admin.entidad', entidad=entidad))
        except ValueError as error:
            flash(str(error), 'error')
        except sqlite3.IntegrityError:
            flash('No se pudo guardar. Revise que el código, el documento o el grupo no estén repetidos.', 'error')
        return redirect(url_for('admin.editar', entidad=entidad, registro_id=registro_id))

    campos = []
    for campo in config['campos']:
        campo = dict(campo)
        campo['valor'] = registro[campo['nombre']]
        if campo.get('tipo') == 'select':
            campo['opciones'] = _opciones(campo)
        campos.append(campo)

    materias_opciones = seleccionadas = hoja = None
    if entidad == 'docentes':
        materias_opciones = _opciones({'opciones_sql': SQL_MATERIAS_OPCIONES})
        seleccionadas = {fila['materia_id'] for fila in db.execute(
            'SELECT materia_id FROM docente_materias WHERE docente_id = ?', (registro_id,)).fetchall()}
        hoja = db.execute(
            'SELECT nombre_original FROM hojas_de_vida WHERE docente_id = ?', (registro_id,)).fetchone()

    return render_template('admin/editar.html', entidad=entidad, config=config, campos=campos,
                           registro_id=registro_id, entidades=ENTIDADES,
                           materias_opciones=materias_opciones, seleccionadas=seleccionadas or set(),
                           hoja=hoja)


@admin_bp.route('/<entidad>/<int:registro_id>/eliminar', methods=['POST'])
@requiere_admin
def eliminar(entidad, registro_id):
    config = _config(entidad)
    db = get_db()
    try:
        if entidad == 'matriculas':
            db.execute(SQL_LIMPIAR_CALIFICACION, (registro_id, registro_id))
        db.execute(f'DELETE FROM {config["tabla"]} WHERE id = ?', (registro_id,))
        db.commit()
        flash('Registro eliminado.', 'ok')
    except sqlite3.IntegrityError:
        flash(f'No se puede eliminar este registro porque tiene datos asociados '
              '(por ejemplo, cursos o estudiantes que dependen de él).', 'error')
    return redirect(url_for('admin.entidad', entidad=entidad))


@admin_bp.route('/accesos', methods=['GET', 'POST'])
@requiere_admin
def accesos():
    db = get_db()

    if request.method == 'POST':
        seleccion = request.form.get('persona', '')
        correo = request.form.get('correo', '').strip().lower()
        contrasena = request.form.get('contrasena', '')

        rol, _, persona_id = seleccion.partition(':')
        if rol not in ROLES_CUENTA or not persona_id.isdigit():
            flash('Seleccione una persona.', 'error')
        elif not correo or '@' not in correo:
            flash('Escriba un correo válido.', 'error')
        elif len(contrasena) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'error')
        else:
            columna = 'docente_id' if rol == 'docente' else 'estudiante_id'
            try:
                db.execute(
                    f'INSERT INTO usuarios (correo, contrasena_hash, rol, {columna}) VALUES (?, ?, ?, ?)',
                    (correo, generate_password_hash(contrasena), rol, int(persona_id)))
                db.commit()
                flash('Acceso creado correctamente.', 'ok')
            except sqlite3.IntegrityError:
                flash('Ese correo ya tiene un acceso, o la persona no existe.', 'error')
        return redirect(url_for('admin.accesos'))

    cuentas = db.execute(
        "SELECT u.id, u.correo, u.rol, "
        "COALESCE(d.nombres || ' ' || d.apellidos, e.nombres || ' ' || e.apellidos) AS persona "
        "FROM usuarios u "
        "LEFT JOIN docentes d ON d.id = u.docente_id "
        "LEFT JOIN estudiantes e ON e.id = u.estudiante_id "
        "ORDER BY u.rol, persona").fetchall()

    personas = []
    for rol, (tabla, etiqueta) in ROLES_CUENTA.items():
        filas = db.execute(
            f"SELECT id, nombres || ' ' || apellidos AS nombre FROM {tabla} ORDER BY apellidos, nombres"
        ).fetchall()
        personas += [(f'{rol}:{fila["id"]}', f'{etiqueta} · {fila["nombre"]}') for fila in filas]

    return render_template('admin/accesos.html', cuentas=cuentas, personas=personas,
                           entidades=ENTIDADES)


@admin_bp.route('/accesos/<int:cuenta_id>/eliminar', methods=['POST'])
@requiere_admin
def eliminar_acceso(cuenta_id):
    db = get_db()
    db.execute('DELETE FROM usuarios WHERE id = ?', (cuenta_id,))
    db.commit()
    flash('Acceso eliminado.', 'ok')
    return redirect(url_for('admin.accesos'))
