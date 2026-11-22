import datetime
import uuid
import io


from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, send_from_directory, url_for
from werkzeug.security import generate_password_hash

from nucleo.db import IntegrityError, get_db
from servicios import estudiantes_csv, notas
from servicios import matricula_financiera as mf
from nucleo.sedes import correo_en_uso
from nucleo.auditoria import registrar
from servicios.documentos import DOCS_DIR
from servicios.comprobante import generar_comprobante
from servicios import documentos_docente as docs_docente
from servicios import hojas as hojas_mod
from nucleo.seguridad import requiere_rol


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
    'personal': {
        'titulo': 'Personal',
        'singular': 'persona del personal',
        'tabla': 'personal',
        'consulta': ("SELECT id, nombres, apellidos, documento, correo, "
                     "CASE tipo WHEN 'administrativo' THEN 'Administrativo' ELSE 'Auxiliar' END AS cargo "
                     "FROM personal ORDER BY apellidos, nombres"),
        'columnas': [('Nombres', 'nombres'), ('Apellidos', 'apellidos'), ('Documento', 'documento'),
                     ('Correo', 'correo'), ('Cargo', 'cargo')],
        'campos': [
            {'nombre': 'nombres', 'etiqueta': 'Nombres', 'requerido': True},
            {'nombre': 'apellidos', 'etiqueta': 'Apellidos', 'requerido': True},
            {'nombre': 'documento', 'etiqueta': 'Documento', 'requerido': True},
            {'nombre': 'correo', 'etiqueta': 'Correo', 'tipo': 'email'},
            {'nombre': 'tipo', 'etiqueta': 'Cargo', 'tipo': 'select', 'requerido': True,
             'opciones_sql': ("SELECT 'administrativo' AS id, 'Administrativo' AS texto "
                              "UNION ALL SELECT 'auxiliar', 'Auxiliar'"),
             'ayuda': 'Después cree su acceso desde la sección Crear acceso.'},
        ],
    },
    'docentes': {
        'titulo': 'Docentes',
        'singular': 'docente',
        'tabla': 'docentes',
        'consulta': ("SELECT d.id, d.nombres, d.apellidos, d.documento, d.correo, d.especialidad, "
                     "(SELECT string_agg(m.nombre, ', ') FROM docente_materias dm "
                     " JOIN materias m ON m.id = dm.materia_id WHERE dm.docente_id = d.id) AS materias, "
                     "(SELECT h.nombre_original FROM hojas_de_vida h WHERE h.docente_id = d.id) AS hoja "
                     "FROM docentes d ORDER BY d.apellidos, d.nombres"),
        'columnas': [('Nombres', 'nombres'), ('Apellidos', 'apellidos'),
                     ('Documento', 'documento'), ('Correo', 'correo'),
                     ('Materias que puede dictar', 'materias'), ('Hoja de vida', 'hoja')],
        'campos': [
            {'nombre': 'nombres', 'etiqueta': 'Nombres', 'requerido': True},
            {'nombre': 'apellidos', 'etiqueta': 'Apellidos', 'requerido': True},
            {'nombre': 'correo', 'etiqueta': 'Correo', 'tipo': 'email', 'requerido': True},
            {'nombre': 'contrasena', 'etiqueta': 'Clave temporal', 'tipo': 'password', 'requerido': True,
             'no_columna': True, 'ayuda': 'Mínimo 6 caracteres. El docente la cambiará al ingresar.'},
        ],
    },
    'materias': {
        'titulo': 'Materias',
        'singular': 'materia',
        'tabla': 'materias',
        'consulta': ("SELECT m.id, m.codigo, m.nombre, m.creditos, m.ciclo, j.nombre AS jornada "
                     "FROM materias m LEFT JOIN jornadas j ON j.id = m.jornada_id "
                     "ORDER BY m.ciclo, m.nombre"),
        'columnas': [('Código', 'codigo'), ('Nombre', 'nombre'), ('Créditos', 'creditos'),
                     ('Ciclo', 'ciclo'), ('Jornada', 'jornada')],
        'campos': [
            {'nombre': 'codigo', 'etiqueta': 'Código', 'requerido': True, 'ejemplo': 'SIS-101'},
            {'nombre': 'nombre', 'etiqueta': 'Nombre', 'requerido': True},
            {'nombre': 'creditos', 'etiqueta': 'Créditos', 'tipo': 'number', 'ejemplo': '3'},
            {'nombre': 'ciclo', 'etiqueta': 'Ciclo (semestre)', 'tipo': 'number', 'requerido': True,
             'minimo': 1, 'maximo': 10, 'ejemplo': '1', 'ayuda': 'Semestre en el que se dicta, de 1 a 10.'},
            {'nombre': 'jornada_id', 'etiqueta': 'Jornada', 'tipo': 'select',
             'opciones_sql': 'SELECT id, nombre AS texto FROM jornadas ORDER BY nombre',
             'ayuda': 'Jornada en la que se dicta la materia.'},
        ],
    },
    'cursos': {
        'titulo': 'Cursos',
        'singular': 'curso',
        'tabla': 'cursos',
        'consulta': ("SELECT c.id, m.nombre AS materia, c.ciclo, c.grupo, c.periodo, c.horario, "
                     "COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente, j.nombre AS jornada, c.cupo "
                     "FROM cursos c "
                     "JOIN materias m ON m.id = c.materia_id "
                     "LEFT JOIN docentes d ON d.id = c.docente_id "
                     "JOIN jornadas j ON j.id = c.jornada_id "
                     "ORDER BY c.periodo DESC, c.ciclo, m.nombre, c.grupo"),
        'columnas': [('Materia', 'materia'), ('Ciclo', 'ciclo'), ('Grupo', 'grupo'), ('Periodo', 'periodo'),
                     ('Docente', 'docente'), ('Jornada', 'jornada'), ('Horario', 'horario'), ('Cupo', 'cupo')],
        'campos': [
            {'nombre': 'materia_id', 'etiqueta': 'Materia', 'tipo': 'select', 'requerido': True,
             'opciones_sql': 'SELECT id, nombre || \' (\' || codigo || \')\' AS texto FROM materias ORDER BY nombre'},
        ],
    },
    'estudiantes': {
        'titulo': 'Estudiantes',
        'singular': 'estudiante',
        'tabla': 'estudiantes',
        'filtros': True,
        'consulta': ("SELECT e.id, e.codigo, e.nombres || ' ' || e.apellidos AS nombre, "
                     "e.documento, e.correo, e.programa, j.nombre AS jornada, "
                     "CASE WHEN EXISTS (SELECT 1 FROM usuarios u WHERE u.estudiante_id = e.id) "
                     "THEN 'Habilitado' ELSE 'Sin acceso' END AS acceso, "
                     "EXISTS (SELECT 1 FROM aspirantes a WHERE a.estudiante_id = e.id OR a.documento = e.documento) AS inscrito, "
                     "e.jornada_id AS jornada_id, "
                     "(SELECT string_agg(DISTINCT c.grupo_id::text, ',') FROM matriculas mt JOIN cursos c ON c.id = mt.curso_id "
                     "WHERE mt.estudiante_id = e.id) AS cursos_ids "
                     "FROM estudiantes e LEFT JOIN jornadas j ON j.id = e.jornada_id "
                     "ORDER BY e.apellidos, e.nombres"),
        'columnas': [('Código', 'codigo'), ('Nombre', 'nombre'), ('Documento', 'documento'),
                     ('Programa', 'programa'), ('Jornada', 'jornada'), ('Acceso a la plataforma', 'acceso')],
        'campos': [
            {'nombre': 'codigo', 'etiqueta': 'Código', 'requerido': True},
            {'nombre': 'nombres', 'etiqueta': 'Nombres', 'requerido': True},
            {'nombre': 'apellidos', 'etiqueta': 'Apellidos', 'requerido': True},
            {'nombre': 'documento', 'etiqueta': 'Documento', 'requerido': True},
            {'nombre': 'correo', 'etiqueta': 'Correo', 'tipo': 'email'},
            {'nombre': 'programa', 'etiqueta': 'Programa', 'tipo': 'select', 'solo_texto': True,
             'opciones_sql': ("SELECT g.grupo || ' · ' || g.periodo AS id, "
                              "'Ciclo ' || COALESCE(CAST(g.ciclo AS TEXT), '-') || ' · ' || g.grupo || ' · ' || g.periodo AS texto "
                              "FROM grupos_curso g ORDER BY g.periodo DESC, g.ciclo, g.grupo"),
             'ayuda': 'Curso al que pertenece el estudiante.'},
            {'nombre': 'jornada_id', 'etiqueta': 'Jornada', 'tipo': 'select',
             'opciones_sql': 'SELECT id, nombre AS texto FROM jornadas ORDER BY nombre'},
            {'nombre': 'fecha_nacimiento', 'etiqueta': 'Fecha de nacimiento', 'tipo': 'date'},
            {'nombre': 'estado_civil', 'etiqueta': 'Estado civil', 'tipo': 'select',
             'opciones_sql': "SELECT 'Soltero(a)' AS id, 'Soltero(a)' AS texto UNION ALL SELECT 'Casado(a)', 'Casado(a)' "
                              "UNION ALL SELECT 'Unión libre', 'Unión libre' UNION ALL SELECT 'Divorciado(a)', 'Divorciado(a)' "
                              "UNION ALL SELECT 'Viudo(a)', 'Viudo(a)'"},
            {'nombre': 'tipo_sangre', 'etiqueta': 'Tipo de sangre', 'tipo': 'select',
             'opciones_sql': "SELECT 'O+' AS id, 'O+' AS texto UNION ALL SELECT 'O-', 'O-' UNION ALL SELECT 'A+', 'A+' "
                              "UNION ALL SELECT 'A-', 'A-' UNION ALL SELECT 'B+', 'B+' UNION ALL SELECT 'B-', 'B-' "
                              "UNION ALL SELECT 'AB+', 'AB+' UNION ALL SELECT 'AB-', 'AB-'"},
            {'nombre': 'lugar_expedicion', 'etiqueta': 'Lugar de expedición del documento'},
            {'nombre': 'fecha_expedicion', 'etiqueta': 'Fecha de expedición del documento', 'tipo': 'date'},
            {'nombre': 'tiene_discapacidad', 'etiqueta': '¿Tiene alguna discapacidad?', 'tipo': 'select',
             'opciones_sql': "SELECT 'Sí' AS id, 'Sí' AS texto UNION ALL SELECT 'No', 'No'"},
            {'nombre': 'discapacidad', 'etiqueta': 'Especifique la discapacidad'},
        ],
    },
    'calificaciones': {
        'titulo': 'Calificaciones',
        'singular': 'calificación',
        'tabla': 'calificaciones',
        'solo_lectura': True,  # las notas se registran desde la vista por cursos
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
        'filtros': True,
        'consulta': ("SELECT mt.id, e.codigo, e.apellidos || ' ' || e.nombres AS estudiante, "
                     "m.nombre AS materia, c.grupo, c.periodo, c.grupo_id AS cursos_ids, e.jornada_id AS jornada_id, "
                     "COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente "
                     "FROM matriculas mt "
                     "JOIN estudiantes e ON e.id = mt.estudiante_id "
                     "JOIN cursos c ON c.id = mt.curso_id "
                     "JOIN materias m ON m.id = c.materia_id "
                     "LEFT JOIN docentes d ON d.id = c.docente_id "
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
    'requisitos': {
        'titulo': 'Requisitos',
        'singular': 'requisito',
        'tabla': 'requisitos',
        'consulta': ("SELECT id, nombre, descripcion, "
                     "CASE WHEN obligatorio = 1 THEN 'Sí' ELSE 'No' END AS obligatorio, "
                     "CASE WHEN formatos = 'imagen' THEN 'PDF, JPG o PNG' ELSE 'PDF' END AS formatos, "
                     "CASE WHEN activo = 1 THEN 'Sí' ELSE 'No' END AS activo "
                     "FROM requisitos ORDER BY activo DESC, obligatorio DESC, nombre"),
        'columnas': [('Requisito', 'nombre'), ('Descripción', 'descripcion'),
                     ('Formato', 'formatos'), ('Obligatorio', 'obligatorio'), ('Se pide', 'activo')],
        'campos': [
            {'nombre': 'nombre', 'etiqueta': 'Nombre del requisito', 'requerido': True,
             'ejemplo': 'Documento de identidad'},
            {'nombre': 'descripcion', 'etiqueta': 'Descripción', 'tipo': 'textarea',
             'ayuda': 'Qué debe contener el documento. Se muestra al aspirante.'},
            {'nombre': 'formatos', 'etiqueta': 'Formato del archivo', 'tipo': 'select', 'requerido': True,
             'opciones_sql': "SELECT 'pdf' AS id, 'PDF' AS texto UNION ALL SELECT 'imagen', 'PDF, JPG o PNG'",
             'ayuda': 'Las fotografías se suben como imagen; los demás documentos como PDF.'},
            {'nombre': 'obligatorio', 'etiqueta': 'Obligatorio', 'tipo': 'select', 'requerido': True,
             'opciones_sql': "SELECT 1 AS id, 'Sí' AS texto UNION ALL SELECT 0, 'No'",
             'ayuda': 'Si es obligatorio, el aspirante no cumple hasta que se apruebe.'},
            {'nombre': 'activo', 'etiqueta': 'Se pide al aspirante', 'tipo': 'select', 'requerido': True,
             'opciones_sql': "SELECT 1 AS id, 'Sí' AS texto UNION ALL SELECT 0, 'No'",
             'ayuda': 'Si es No, el documento deja de pedirse, pero no se borra lo ya subido.'},
        ],
    },
    'aspirantes': {
        'titulo': 'Aspirantes',
        'singular': 'aspirante',
        'tabla': 'aspirantes',
        'solo_lectura': True,  # se inscriben desde la página pública
        'consulta': ("SELECT a.id, a.nombres || ' ' || a.apellidos AS nombre, a.documento, a.correo, "
                     "a.programa, j.nombre AS jornada, a.estado, "
                     "(SELECT COUNT(*) FROM requisitos r JOIN documentos_aspirante d "
                     "   ON d.requisito_id = r.id AND d.aspirante_id = a.id "
                     " WHERE r.obligatorio = 1 AND d.estado = 'aprobado') || ' de ' || "
                     "(SELECT COUNT(*) FROM requisitos WHERE obligatorio = 1 AND activo = 1) || ' aprobados' AS documentos, "
                     "a.creado_en, a.estudiante_id, (a.estado = 'habilitado') AS habilitado, "
                     "(SELECT COUNT(*) FROM requisitos r JOIN documentos_aspirante d "
                     "   ON d.requisito_id = r.id AND d.aspirante_id = a.id "
                     " WHERE r.obligatorio = 1 AND r.activo = 1 AND d.estado = 'aprobado') = "
                     "(SELECT COUNT(*) FROM requisitos WHERE obligatorio = 1 AND activo = 1) AS cumple "
                     "FROM aspirantes a LEFT JOIN jornadas j ON j.id = a.jornada_id "
                     "ORDER BY a.creado_en DESC"),
        'columnas': [('Nombre', 'nombre'), ('Documento', 'documento'), ('Correo', 'correo'),
                     ('Programa', 'programa'), ('Jornada', 'jornada'), ('Estado', 'estado'),
                     ('Documentos obligatorios', 'documentos'), ('Inscrito el', 'creado_en')],
        'campos': [],
    },
}

# Tipos de persona que pueden tener una cuenta: (tabla, etiqueta)
# Cada tipo: (tabla, etiqueta, columna que lo identifica en usuarios, filtro sobre la tabla)
ROLES_CUENTA = {
    'docente': ('docentes', 'Docente', 'docente_id', ''),
    'estudiante': ('estudiantes', 'Estudiante', 'estudiante_id', ''),
    'administrativo': ('personal', 'Administrativo', 'personal_id', "WHERE tipo = 'administrativo'"),
    'auxiliar': ('personal', 'Auxiliar', 'personal_id', "WHERE tipo = 'auxiliar'"),
}


# Ranking de cursos por promedio de notas. Solo cuentan los cursos con al menos una nota.
CONSULTA_RANKING = """
SELECT c.id, m.nombre AS materia, c.grupo, c.periodo,
       COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente,
       AVG(k.nota) AS promedio, COUNT(k.id) AS evaluados
FROM calificaciones k
JOIN cursos c ON c.id = k.curso_id
JOIN materias m ON m.id = c.materia_id
LEFT JOIN docentes d ON d.id = c.docente_id
GROUP BY c.id, m.nombre, c.grupo, c.periodo, d.nombres, d.apellidos
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
        if campo.get('no_columna'):
            continue
        bruto = request.form.get(campo['nombre'], '').strip()
        etiqueta = campo['etiqueta']

        if campo.get('requerido') and not bruto:
            raise ValueError(f'El campo {etiqueta} es obligatorio.')

        if campo.get('tipo') == 'number':
            try:
                valor = int(bruto or 0)
            except ValueError:
                raise ValueError(f'{etiqueta} debe ser un número entero.')
            if 'minimo' in campo and not campo['minimo'] <= valor <= campo['maximo']:
                raise ValueError(f'{etiqueta} debe estar entre {campo["minimo"]} y {campo["maximo"]}.')
            valores[campo['nombre']] = valor
        elif campo.get('tipo') == 'decimal':
            try:
                valor = float(bruto.replace(',', '.')) if bruto else None
            except ValueError:
                raise ValueError(f'{etiqueta} debe ser un número.')
            if valor is not None and not campo['minimo'] <= valor <= campo['maximo']:
                raise ValueError(f'{etiqueta} debe estar entre {campo["minimo"]} y {campo["maximo"]}.')
            valores[campo['nombre']] = valor
        elif campo.get('tipo') == 'date':
            if bruto:
                try:
                    datetime.date.fromisoformat(bruto)
                except ValueError:
                    raise ValueError(f'{etiqueta} debe ser una fecha válida.')
            valores[campo['nombre']] = bruto or None
        elif campo.get('tipo') == 'select':
            # Los menús pueden devolver números (ids) o textos (por ejemplo, 'pdf' o 'imagen')
            if not bruto:
                valores[campo['nombre']] = None
            else:
                valores[campo['nombre']] = bruto if campo.get('solo_texto') or not bruto.isdigit() else int(bruto)
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
    """Guarda las materias habilitadas que vienen en el formulario de docente."""
    db = get_db()
    for materia in request.form.getlist('materias'):
        if materia.isdigit():
            db.execute('INSERT OR IGNORE INTO docente_materias (docente_id, materia_id) VALUES (?, ?)',
                       (docente_id, int(materia)))
    db.commit()


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
    # Los cursos se crean desde su propia página (con las materias marcadas), no desde este formulario
    if (config.get('solo_lectura') or entidad == 'cursos') and request.method == 'POST':
        abort(405)

    if request.method == 'POST':
        try:
            valores = _valores_del_formulario(config)
            if entidad == 'cursos' and valores.get('docente_id') and not _docente_puede_dictar(valores['docente_id'], valores['materia_id']):
                raise ValueError('Ese docente no está habilitado para dictar esa materia. '
                                 'Revise las materias que puede dictar en su registro.')
            clave = request.form.get('contrasena', '')
            if entidad == 'docentes':
                if len(clave) < 6:
                    raise ValueError('La clave temporal debe tener al menos 6 caracteres.')
                valores['correo'] = (valores.get('correo') or '').lower()
                if correo_en_uso(valores['correo']):
                    raise ValueError('Ese correo ya tiene una cuenta en la plataforma.')
                # El documento real lo registra el docente en Mis datos
                valores['documento'] = f'PENDIENTE-{uuid.uuid4().hex[:8]}'
            columnas = ', '.join(valores)
            marcas = ', '.join('?' for _ in valores)
            cursor = db.execute(f'INSERT INTO {config["tabla"]} ({columnas}) VALUES ({marcas})',
                                list(valores.values()))
            if entidad == 'docentes':
                db.execute("INSERT INTO usuarios (correo, contrasena_hash, rol, docente_id) VALUES (?, ?, 'docente', ?)",
                           (valores['correo'], generate_password_hash(clave), cursor.lastrowid))
            registrar(db, 'crear', f'{config["singular"]} id {cursor.lastrowid}')
            db.commit()
            flash('Docente creado. Ya puede ingresar con su correo y la clave temporal.' if entidad == 'docentes'
                  else 'Registro guardado correctamente.', 'ok')
        except ValueError as error:
            flash(str(error), 'error')
        except IntegrityError:
            flash('No se pudo guardar. Revise que el código, el documento o el grupo no estén '
                  'repetidos y que las relaciones seleccionadas existan.', 'error')
        return redirect(url_for('admin.entidad', entidad=entidad))

    if entidad == 'cursos':
        return _vista_ciclos()
    if entidad == 'calificaciones':
        return _vista_calificaciones()

    filas = db.execute(config['consulta']).fetchall()
    campos = []
    for campo in config['campos']:
        campo = dict(campo)
        if campo.get('tipo') == 'select':
            campo['opciones'] = _opciones(campo)
        campos.append(campo)

    materias_opciones = None
    datos_extra = _datos_nuevo_curso() if entidad == 'cursos' else {}
    cursos_filtro, jornadas_filtro = mf.opciones_filtro() if config.get('filtros') else ([], [])
    return render_template('admin/entidad.html', entidad=entidad, config=config,
                           filas=filas, campos=campos, entidades=ENTIDADES,
                           materias_opciones=materias_opciones, seleccionadas=set(),
                           editando=False, registro_id=None, cursos=cursos_filtro, jornadas=jornadas_filtro,
                           **datos_extra)


CICLOS_PLAN = ('1', '2', '3', '4', '5', '6')


def _datos_nuevo_curso():
    """Materias con sus docentes habilitados, para agregar materias a un curso; y jornadas y ciclos."""
    db = get_db()
    materias_json = []
    for materia in db.execute('SELECT id, nombre, codigo FROM materias ORDER BY nombre').fetchall():
        docentes = db.execute(
            "SELECT d.id, d.nombres || ' ' || d.apellidos AS texto FROM docentes d "
            "JOIN docente_materias dm ON dm.docente_id = d.id "
            "WHERE dm.materia_id = ? ORDER BY d.apellidos, d.nombres", (materia['id'],)).fetchall()
        materias_json.append({'id': materia['id'], 'nombre': materia['nombre'], 'codigo': materia['codigo'],
                              'docentes': [{'id': d['id'], 'texto': d['texto']} for d in docentes]})
    jornadas = db.execute('SELECT id, nombre FROM jornadas ORDER BY nombre').fetchall()
    return {'materias_json': materias_json, 'jornadas': jornadas, 'ciclos': CICLOS_PLAN}


def _vista_ciclos():
    """Lista de ciclos (1 a 6) con cuántos cursos y materias tiene cada uno."""
    db = get_db()
    grupos = {fila['ciclo']: fila['grupos'] for fila in db.execute(
        'SELECT ciclo, COUNT(*) AS grupos FROM grupos_curso GROUP BY ciclo').fetchall()}
    materias = {fila['ciclo']: fila['materias'] for fila in db.execute(
        'SELECT g.ciclo, COUNT(c.id) AS materias FROM grupos_curso g '
        'LEFT JOIN cursos c ON c.grupo_id = g.id GROUP BY g.ciclo').fetchall()}
    tarjetas = [{'numero': n, 'cursos': grupos.get(n, 0), 'materias': materias.get(n, 0)} for n in range(1, 7)]
    return render_template('admin/cursos_ciclos.html', tarjetas=tarjetas, sin_ciclo=grupos.get(None),
                           entidad='cursos', entidades=ENTIDADES, preseleccion=None, **_datos_nuevo_curso())


@admin_bp.route('/cursos/nuevo', methods=['GET', 'POST'])
@requiere_admin
def nuevo_curso():
    """Crea el curso de un ciclo (grupo, periodo y jornada). Sus materias se agregan después."""
    if request.method == 'GET':
        return redirect(url_for('admin.entidad', entidad='cursos'))
    db = get_db()
    ciclo = request.form.get('ciclo', '')
    letra = request.form.get('grupo', '').strip().upper()
    periodo = request.form.get('periodo', '').strip()
    jornada_id = request.form.get('jornada_id', '')
    horario = request.form.get('horario', '').strip() or None
    cupo = request.form.get('cupo', '').strip() or '0'
    try:
        if ciclo not in CICLOS_PLAN:
            raise ValueError('Seleccione el ciclo (del 1 al 6).')
        if not letra:
            raise ValueError('Escriba la letra del grupo, por ejemplo A.')
        if not periodo:
            raise ValueError('Escriba el periodo, por ejemplo 2026-B.')
        if not jornada_id.isdigit():
            raise ValueError('Seleccione la jornada.')
        if not cupo.isdigit():
            raise ValueError('El cupo debe ser un número entero.')
        grupo = f'{ciclo}{letra}'
        cursor = db.execute(
            'INSERT INTO grupos_curso (ciclo, grupo, periodo, jornada_id, horario, cupo) VALUES (?, ?, ?, ?, ?, ?)',
            (int(ciclo), grupo, periodo, int(jornada_id), horario, int(cupo)))
        registrar(db, 'crear', f'Curso {grupo} del periodo {periodo}')
        db.commit()
        flash(f'Curso {grupo} creado para el periodo {periodo}. Ahora agregue sus materias.', 'ok')
        return redirect(url_for('admin.curso_grupo', grupo_id=cursor.lastrowid))
    except ValueError as error:
        db.rollback()
        flash(str(error), 'error')
    except IntegrityError:
        db.rollback()
        flash(f'Ya existe el curso {ciclo}{letra} en el periodo {periodo}. Use otra letra de grupo.', 'error')
    destino = url_for('admin.vista_ciclo', ciclo=ciclo) if ciclo in CICLOS_PLAN else url_for('admin.entidad', entidad='cursos')
    return redirect(destino)


@admin_bp.route('/cursos/ciclo/<ciclo>')
@requiere_admin
def vista_ciclo(ciclo):
    """Cursos de un ciclo. «sin» muestra los que todavía no tienen ciclo."""
    if ciclo not in CICLOS_PLAN and ciclo != 'sin':
        abort(404)
    condicion, parametros = ('g.ciclo IS NULL', ()) if ciclo == 'sin' else ('g.ciclo = ?', (int(ciclo),))
    grupos = get_db().execute(
        "SELECT g.id, g.grupo, g.periodo, g.horario, g.cupo, j.nombre AS jornada, "
        "(SELECT COUNT(*) FROM cursos c WHERE c.grupo_id = g.id) AS materias "
        "FROM grupos_curso g JOIN jornadas j ON j.id = g.jornada_id "
        f"WHERE {condicion} ORDER BY g.periodo DESC, g.grupo", parametros).fetchall()
    return render_template('admin/cursos_ciclo.html', ciclo=ciclo, grupos=grupos, entidad='cursos',
                           entidades=ENTIDADES, preseleccion=None if ciclo == 'sin' else ciclo,
                           **_datos_nuevo_curso())


@admin_bp.route('/cursos/grupo/<int:grupo_id>')
@requiere_admin
def curso_grupo(grupo_id):
    """Un curso con sus materias y sus docentes."""
    db = get_db()
    grupo = db.execute(
        "SELECT g.id, g.ciclo, g.grupo, g.periodo, g.horario, g.cupo, j.nombre AS jornada "
        "FROM grupos_curso g JOIN jornadas j ON j.id = g.jornada_id WHERE g.id = ?", (grupo_id,)).fetchone()
    if grupo is None:
        abort(404)
    materias = db.execute(
        "SELECT c.id, m.nombre AS materia, m.codigo, "
        "COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente, "
        "(SELECT COUNT(*) FROM matriculas mt WHERE mt.curso_id = c.id) AS estudiantes "
        "FROM cursos c JOIN materias m ON m.id = c.materia_id "
        "LEFT JOIN docentes d ON d.id = c.docente_id "
        "WHERE c.grupo_id = ? ORDER BY m.nombre", (grupo_id,)).fetchall()
    estudiantes = db.execute(
        "SELECT DISTINCT e.id, e.codigo, e.documento, e.apellidos || ' ' || e.nombres AS nombre "
        "FROM matriculas mt JOIN cursos c ON c.id = mt.curso_id "
        "JOIN estudiantes e ON e.id = mt.estudiante_id "
        "WHERE c.grupo_id = ? ORDER BY e.apellidos, e.nombres", (grupo_id,)).fetchall()
    # Estudiantes que todavía no están en este curso, para la ventana de matrícula
    disponibles = db.execute(
        "SELECT e.id, e.codigo, e.documento, e.apellidos || ' ' || e.nombres AS nombre FROM estudiantes e "
        "WHERE e.id NOT IN (SELECT mt.estudiante_id FROM matriculas mt JOIN cursos c ON c.id = mt.curso_id "
        "WHERE c.grupo_id = ?) ORDER BY e.apellidos, e.nombres", (grupo_id,)).fetchall()
    estudiantes_json = [{'id': e['id'], 'codigo': e['codigo'], 'documento': e['documento'], 'nombre': e['nombre']}
                        for e in disponibles]
    return render_template('admin/curso_grupo.html', grupo=grupo, materias=materias, estudiantes=estudiantes,
                           estudiantes_json=estudiantes_json, entidad='cursos', entidades=ENTIDADES,
                           **_datos_nuevo_curso())


@admin_bp.route('/cursos/grupo/<int:grupo_id>/materias', methods=['POST'])
@requiere_admin
def agregar_materias(grupo_id):
    """Agrega materias al curso. Cada una se guarda como un curso con su docente (o sin asignar)."""
    db = get_db()
    grupo = db.execute('SELECT * FROM grupos_curso WHERE id = ?', (grupo_id,)).fetchone()
    if grupo is None:
        abort(404)
    marcadas = [m for m in request.form.getlist('materias') if m.isdigit()]
    try:
        if not marcadas:
            raise ValueError('Agregue al menos una materia al curso.')
        asignaciones = []
        for materia_id in marcadas:
            docente_id = request.form.get(f'docente_{materia_id}', '')
            nombre = db.execute('SELECT nombre FROM materias WHERE id = ?', (materia_id,)).fetchone()
            if nombre is None:
                raise ValueError('Una de las materias ya no existe.')
            if docente_id and not (docente_id.isdigit() and _docente_puede_dictar(int(docente_id), int(materia_id))):
                raise ValueError(f'El docente elegido no está habilitado para {nombre["nombre"]}.')
            asignaciones.append((int(materia_id), int(docente_id) if docente_id else None))
        for materia_id, docente_id in asignaciones:
            db.execute(
                'INSERT INTO cursos (materia_id, docente_id, jornada_id, periodo, grupo, ciclo, horario, cupo, grupo_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (materia_id, docente_id, grupo['jornada_id'], grupo['periodo'], grupo['grupo'], grupo['ciclo'],
                 grupo['horario'], grupo['cupo'], grupo_id))
        # Los estudiantes que ya están en el curso también cursan las materias nuevas
        db.execute(
            'INSERT OR IGNORE INTO matriculas (curso_id, estudiante_id) '
            'SELECT c.id, e.estudiante_id FROM cursos c '
            'CROSS JOIN (SELECT DISTINCT mt.estudiante_id FROM matriculas mt '
            '            JOIN cursos cg ON cg.id = mt.curso_id WHERE cg.grupo_id = ?) e '
            'WHERE c.grupo_id = ?',
            (grupo_id, grupo_id))
        registrar(db, 'agregar_materias', f'{len(asignaciones)} materia(s) en el curso id {grupo_id}')
        db.commit()
        flash(f'Se agregaron {len(asignaciones)} materia(s) al curso {grupo["grupo"]}.', 'ok')
    except ValueError as error:
        db.rollback()
        flash(str(error), 'error')
    except IntegrityError:
        db.rollback()
        flash('Alguna de esas materias ya está en este curso.', 'error')
    return redirect(url_for('admin.curso_grupo', grupo_id=grupo_id))


@admin_bp.route('/cursos/grupo/<int:grupo_id>/eliminar', methods=['POST'])
@requiere_admin
def eliminar_grupo(grupo_id):
    db = get_db()
    grupo = db.execute('SELECT ciclo FROM grupos_curso WHERE id = ?', (grupo_id,)).fetchone()
    if grupo is None:
        abort(404)
    if db.execute('SELECT 1 FROM cursos WHERE grupo_id = ?', (grupo_id,)).fetchone():
        flash('Este curso tiene materias. Elimínelas primero.', 'error')
        return redirect(url_for('admin.curso_grupo', grupo_id=grupo_id))
    db.execute('DELETE FROM grupos_curso WHERE id = ?', (grupo_id,))
    registrar(db, 'eliminar', f'Curso id {grupo_id}')
    db.commit()
    flash('Curso eliminado.', 'ok')
    return redirect(url_for('admin.vista_ciclo', ciclo=grupo['ciclo'] if grupo['ciclo'] else 'sin'))


@admin_bp.route('/cursos/grupo/<int:grupo_id>/estudiantes', methods=['POST'])
@requiere_admin
def agregar_estudiantes(grupo_id):
    """Matricula estudiantes en el curso: quedan inscritos en todas sus materias."""
    db = get_db()
    if db.execute('SELECT 1 FROM grupos_curso WHERE id = ?', (grupo_id,)).fetchone() is None:
        abort(404)
    ids = sorted({e for e in request.form.getlist('estudiantes') if e.isdigit()}, key=int)
    if not ids:
        flash('Agregue al menos un estudiante.', 'error')
        return redirect(url_for('admin.curso_grupo', grupo_id=grupo_id))
    cursos_ids = [fila['id'] for fila in db.execute(
        'SELECT id FROM cursos WHERE grupo_id = ?', (grupo_id,)).fetchall()]
    if not cursos_ids:
        flash('Este curso todavía no tiene materias. Agregue materias antes de matricular estudiantes.', 'error')
        return redirect(url_for('admin.curso_grupo', grupo_id=grupo_id))
    try:
        for estudiante_id in ids:
            for curso_id in cursos_ids:
                db.execute('INSERT OR IGNORE INTO matriculas (curso_id, estudiante_id) VALUES (?, ?)',
                           (curso_id, int(estudiante_id)))
        registrar(db, 'matricular', f'{len(ids)} estudiante(s) en el curso id {grupo_id}')
        db.commit()
        flash(f'Se matricularon {len(ids)} estudiante(s) en las {len(cursos_ids)} materia(s) del curso.', 'ok')
    except IntegrityError:
        db.rollback()
        flash('No se pudo matricular: alguno de los estudiantes ya no existe.', 'error')
    return redirect(url_for('admin.curso_grupo', grupo_id=grupo_id))


@admin_bp.route('/cursos/grupo/<int:grupo_id>/estudiantes/<int:estudiante_id>/quitar', methods=['POST'])
@requiere_admin
def quitar_estudiante(grupo_id, estudiante_id):
    db = get_db()
    tiene_notas = db.execute(
        'SELECT 1 FROM calificaciones k JOIN cursos c ON c.id = k.curso_id '
        'WHERE c.grupo_id = ? AND k.estudiante_id = ? '
        'UNION ALL '
        'SELECT 1 FROM notas_criterio np JOIN criterios_evaluacion cr ON cr.id = np.criterio_id '
        'JOIN cursos c ON c.id = cr.curso_id WHERE c.grupo_id = ? AND np.estudiante_id = ? LIMIT 1',
        (grupo_id, estudiante_id, grupo_id, estudiante_id)).fetchone()
    if tiene_notas:
        flash('No se puede quitar: el estudiante ya tiene notas en este curso.', 'error')
    else:
        db.execute('DELETE FROM matriculas WHERE estudiante_id = ? '
                   'AND curso_id IN (SELECT id FROM cursos WHERE grupo_id = ?)', (estudiante_id, grupo_id))
        registrar(db, 'quitar_estudiante', f'estudiante id {estudiante_id} del curso id {grupo_id}')
        db.commit()
        flash('Estudiante quitado del curso.', 'ok')
    return redirect(url_for('admin.curso_grupo', grupo_id=grupo_id))


@admin_bp.route('/estudiantes/exportar')
@requiere_admin
def exportar_estudiantes():
    """Descarga todos los estudiantes en CSV (solo datos escritos)."""
    contenido = estudiantes_csv.exportar(get_db())
    return send_file(io.BytesIO(contenido), mimetype='text/csv', as_attachment=True,
                     download_name='estudiantes.csv')


@admin_bp.route('/estudiantes/formato')
@requiere_admin
def formato_estudiantes():
    """Plantilla vacía con los encabezados que acepta la importación."""
    return send_file(io.BytesIO(estudiantes_csv.formato()), mimetype='text/csv', as_attachment=True,
                     download_name='formato_estudiantes.csv')


@admin_bp.route('/estudiantes/importar', methods=['POST'])
@requiere_admin
def importar_estudiantes():
    archivo = request.files.get('archivo')
    if archivo is None or not archivo.filename or not archivo.filename.lower().endswith('.csv'):
        flash('Seleccione un archivo .csv.', 'error')
        return redirect(url_for('admin.entidad', entidad='estudiantes'))
    ok, mensajes, creados, actualizados = estudiantes_csv.importar(get_db(), archivo.read())
    if ok:
        db = get_db()
        registrar(db, 'importar', f'{creados} nuevo(s) y {actualizados} actualizado(s) desde CSV')
        db.commit()
        flash(f'Importación lista: {creados} estudiante(s) nuevo(s) y {actualizados} actualizado(s).', 'ok')
    else:
        for mensaje in mensajes:
            flash(mensaje, 'error')
    return redirect(url_for('admin.entidad', entidad='estudiantes'))


@admin_bp.route('/estudiantes/<int:estudiante_id>/acceso/habilitar', methods=['POST'])
@requiere_admin
def habilitar_acceso_estudiante(estudiante_id):
    """Crea la cuenta del estudiante para que entre a la plataforma y vea sus notas."""
    db = get_db()
    estudiante = db.execute('SELECT id, correo FROM estudiantes WHERE id = ?', (estudiante_id,)).fetchone()
    if estudiante is None:
        abort(404)
    if db.execute('SELECT 1 FROM usuarios WHERE estudiante_id = ?', (estudiante_id,)).fetchone():
        flash('Este estudiante ya tiene acceso habilitado.', 'error')
        return redirect(url_for('admin.entidad', entidad='estudiantes'))

    # Si el estudiante se inscribió, entra con el correo y la contraseña de su inscripción
    inscripcion = db.execute(
        'SELECT correo, contrasena_hash FROM aspirantes WHERE estudiante_id = ? OR documento = '
        '(SELECT documento FROM estudiantes WHERE id = ?) LIMIT 1',
        (estudiante_id, estudiante_id)).fetchone()
    if inscripcion is not None:
        correo, hash_clave = inscripcion['correo'].lower(), inscripcion['contrasena_hash']
    else:
        correo = (request.form.get('correo') or estudiante['correo'] or '').strip().lower()
        contrasena = request.form.get('contrasena', '')
        if '@' not in correo:
            flash('Escriba un correo válido para el estudiante.', 'error')
            return redirect(url_for('admin.entidad', entidad='estudiantes'))
        if len(contrasena) < 6:
            flash('Escriba una contraseña inicial de al menos 6 caracteres.', 'error')
            return redirect(url_for('admin.entidad', entidad='estudiantes'))
        hash_clave = generate_password_hash(contrasena)

    if correo_en_uso(correo):
        flash('Ese correo ya tiene una cuenta en la plataforma. Revise el registro del estudiante.', 'error')
    else:
        db.execute("INSERT INTO usuarios (correo, contrasena_hash, rol, estudiante_id) VALUES (?, ?, 'estudiante', ?)",
                   (correo, hash_clave, estudiante_id))
        db.execute('UPDATE estudiantes SET correo = ? WHERE id = ?', (correo, estudiante_id))
        registrar(db, 'acceso_habilitado', f'estudiante id {estudiante_id} con correo {correo}')
        db.commit()
        flash('Acceso habilitado. El estudiante ya puede entrar a la plataforma y ver sus notas.', 'ok')
    return redirect(url_for('admin.entidad', entidad='estudiantes'))


@admin_bp.route('/estudiantes/<int:estudiante_id>/acceso/deshabilitar', methods=['POST'])
@requiere_admin
def deshabilitar_acceso_estudiante(estudiante_id):
    """Quita la cuenta de ingreso. Los datos y las notas del estudiante se conservan."""
    db = get_db()
    db.execute("DELETE FROM usuarios WHERE estudiante_id = ? AND rol = 'estudiante'", (estudiante_id,))
    registrar(db, 'acceso_deshabilitado', f'estudiante id {estudiante_id}')
    db.commit()
    flash('Acceso deshabilitado. El estudiante ya no puede entrar a la plataforma.', 'ok')
    return redirect(url_for('admin.entidad', entidad='estudiantes'))


@admin_bp.route('/calificaciones/plazos', methods=['POST'])
@requiere_admin
def guardar_plazo_notas():
    """Define cuándo abre y cierra el registro de notas de un periodo, o lo cierra de inmediato."""
    db = get_db()
    periodo = request.form.get('periodo', '').strip()
    if not periodo:
        abort(400)
    if request.form.get('accion') == 'cerrar':
        abre = db.execute('SELECT abre FROM plazos_notas WHERE periodo = ?', (periodo,)).fetchone()
        ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        abre_valor = abre['abre'] if abre else None
        if abre_valor and abre_valor > ayer:
            abre_valor = ayer
        db.execute('INSERT INTO plazos_notas (periodo, abre, cierra) VALUES (?, ?, ?) '
                   'ON CONFLICT (periodo) DO UPDATE SET cierra = excluded.cierra, abre = excluded.abre',
                   (periodo, abre_valor, ayer))
        registrar(db, 'plazo_cerrado', f'periodo {periodo}')
        db.commit()
        flash(f'Plazo cerrado para el periodo {periodo}. Los docentes ya no pueden cambiar sus notas.', 'ok')
        return redirect(url_for('admin.entidad', entidad='calificaciones'))

    abre = request.form.get('abre', '').strip() or None
    cierra = request.form.get('cierra', '').strip() or None
    try:
        for valor in (abre, cierra):
            if valor:
                datetime.date.fromisoformat(valor)
    except ValueError:
        flash('Escriba las fechas del plazo con formato válido.', 'error')
        return redirect(url_for('admin.entidad', entidad='calificaciones'))
    if abre and cierra and abre > cierra:
        flash('La fecha de cierre no puede ser anterior a la de apertura.', 'error')
        return redirect(url_for('admin.entidad', entidad='calificaciones'))
    db.execute('INSERT INTO plazos_notas (periodo, abre, cierra) VALUES (?, ?, ?) '
               'ON CONFLICT (periodo) DO UPDATE SET abre = excluded.abre, cierra = excluded.cierra',
               (periodo, abre, cierra))
    registrar(db, 'plazo_guardado', f'periodo {periodo}: abre {abre or "sin fecha"}, cierra {cierra or "sin fecha"}')
    db.commit()
    flash(f'Plazo guardado para el periodo {periodo}.', 'ok')
    return redirect(url_for('admin.entidad', entidad='calificaciones'))


def _vista_calificaciones():
    """Cursos activos (periodo más reciente), con cuántos estudiantes tiene cada uno."""
    db = get_db()
    periodo = db.execute('SELECT periodo FROM cursos ORDER BY periodo DESC LIMIT 1').fetchone()
    cursos = []
    if periodo is not None:
        cursos = db.execute(
            "SELECT c.id, m.nombre AS materia, c.ciclo, c.grupo, c.periodo, c.horario, "
            "COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente, "
            "(SELECT COUNT(*) FROM matriculas mt WHERE mt.curso_id = c.id) AS total "
            "FROM cursos c JOIN materias m ON m.id = c.materia_id "
            "LEFT JOIN docentes d ON d.id = c.docente_id "
            "WHERE c.periodo = ? ORDER BY m.nombre, c.grupo", (periodo['periodo'],)).fetchall()
    return render_template('admin/calificaciones.html', cursos=cursos,
                           periodo=periodo['periodo'] if periodo else None, entidades=ENTIDADES,
                           plazos=notas.plazos())


# Rutas de la pantalla de notas del curso (la misma que usa el docente)
RUTAS_NOTAS_ADMIN = {
    'guardar': 'admin.curso_notas',
    'agregar': 'admin.agregar_criterio',
    'eliminar': 'admin.eliminar_criterio',
    'exportar': 'admin.exportar_notas',
}


def _curso_existente(curso_id):
    curso = get_db().execute(
        "SELECT c.id, c.docente_id, m.nombre AS materia, m.creditos, c.grupo, c.periodo, c.cupo, c.horario, "
        "j.nombre AS jornada, COALESCE(d.nombres || ' ' || d.apellidos, 'Sin asignar') AS docente "
        "FROM cursos c JOIN materias m ON m.id = c.materia_id "
        "JOIN jornadas j ON j.id = c.jornada_id LEFT JOIN docentes d ON d.id = c.docente_id "
        "WHERE c.id = ?", (curso_id,)).fetchone()
    if curso is None:
        abort(404)
    return curso


@admin_bp.route('/calificaciones/curso/<int:curso_id>', methods=['GET', 'POST'])
@requiere_admin
def curso_notas(curso_id):
    curso = _curso_existente(curso_id)
    if request.method == 'POST':
        ok, mensaje = notas.guardar_notas(curso_id, request.form)
        flash(mensaje, 'ok' if ok else 'error')
        return redirect(url_for('admin.curso_notas', curso_id=curso_id))

    criterios, total, estudiantes = notas.estudiantes_con_notas(curso_id)
    return render_template('admin/curso_notas.html', curso=curso, criterios=criterios, total=total,
                           estudiantes=estudiantes, rutas=RUTAS_NOTAS_ADMIN, entidades=ENTIDADES,
                           puede_editar=True, aviso_plazo='')


@admin_bp.route('/calificaciones/curso/<int:curso_id>/criterios', methods=['POST'])
@requiere_admin
def agregar_criterio(curso_id):
    _curso_existente(curso_id)
    ok, mensaje = notas.agregar_criterio(curso_id, request.form.get('nombre'), request.form.get('porcentaje'))
    flash(mensaje, 'ok' if ok else 'error')
    return redirect(url_for('admin.curso_notas', curso_id=curso_id))


@admin_bp.route('/calificaciones/curso/<int:curso_id>/criterios/<int:criterio_id>/eliminar', methods=['POST'])
@requiere_admin
def eliminar_criterio(curso_id, criterio_id):
    _curso_existente(curso_id)
    notas.eliminar_criterio(curso_id, criterio_id)
    flash('Criterio eliminado. Las notas de ese criterio también se borraron.', 'ok')
    return redirect(url_for('admin.curso_notas', curso_id=curso_id))


@admin_bp.route('/calificaciones/curso/<int:curso_id>/exportar/<formato>')
@requiere_admin
def exportar_notas(curso_id, formato):
    _curso_existente(curso_id)
    return notas.respuesta_exportacion(curso_id, formato)


def _materias_del_formulario():
    return [int(m) for m in request.form.getlist('materias') if m.isdigit()]


def _actualizar_extras_docente(docente_id, materias):
    """Reemplaza las materias habilitadas del docente."""
    db = get_db()
    db.execute('DELETE FROM docente_materias WHERE docente_id = ?', (docente_id,))
    for materia_id in materias:
        db.execute('INSERT OR IGNORE INTO docente_materias (docente_id, materia_id) VALUES (?, ?)',
                   (docente_id, materia_id))
    db.commit()


@admin_bp.route('/<entidad>/<int:registro_id>/editar', methods=['GET', 'POST'])
@requiere_admin
def editar(entidad, registro_id):
    config = _config(entidad)
    if config.get('solo_lectura'):
        abort(404)
    db = get_db()
    registro = db.execute(f'SELECT * FROM {config["tabla"]} WHERE id = ?', (registro_id,)).fetchone()
    if registro is None:
        abort(404)

    if request.method == 'POST':
        try:
            valores = _valores_del_formulario(config)
            materias = _materias_del_formulario() if entidad == 'docentes' else []

            if entidad == 'cursos' and valores.get('docente_id') and not _docente_puede_dictar(valores['docente_id'], valores['materia_id']):
                raise ValueError('Ese docente no está habilitado para dictar esa materia. '
                                 'Revise las materias que puede dictar en su registro.')
            if entidad == 'docentes':
                valores['correo'] = (valores.get('correo') or '').lower()
                # El correo es también el usuario de ingreso: no puede estar en otra cuenta
                if db.execute('SELECT 1 FROM usuarios WHERE correo = ? AND docente_id IS NOT ?',
                              (valores['correo'], registro_id)).fetchone():
                    raise ValueError('Ese correo ya tiene una cuenta en la plataforma.')
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
            if entidad == 'docentes':
                db.execute('UPDATE usuarios SET correo = ? WHERE docente_id = ?', (valores['correo'], registro_id))
            registrar(db, 'editar', f'{config["singular"]} id {registro_id}')
            db.commit()
            if entidad == 'docentes':
                _actualizar_extras_docente(registro_id, materias)
            flash('Registro actualizado correctamente.', 'ok')
            return redirect(url_for('admin.entidad', entidad=entidad))
        except ValueError as error:
            flash(str(error), 'error')
        except IntegrityError:
            flash('No se pudo guardar. Revise que el código, el documento o el grupo no estén repetidos.', 'error')
        return redirect(url_for('admin.editar', entidad=entidad, registro_id=registro_id))

    campos = []
    for campo in config['campos']:
        campo = dict(campo)
        # Los campos que no son columna (por ejemplo, la clave temporal) no tienen valor que mostrar
        campo['valor'] = None if campo.get('no_columna') else registro[campo['nombre']]
        if campo.get('tipo') == 'select':
            campo['opciones'] = _opciones(campo)
        if campo.get('solo_texto') and campo['valor'] and campo['valor'] not in [o[0] for o in campo['opciones']]:
            campo['opciones'].append((campo['valor'], campo['valor']))
        campos.append(campo)

    materias_opciones = seleccionadas = None
    if entidad == 'docentes':
        materias_opciones = _opciones({'opciones_sql': SQL_MATERIAS_OPCIONES})
        seleccionadas = {fila['materia_id'] for fila in db.execute(
            'SELECT materia_id FROM docente_materias WHERE docente_id = ?', (registro_id,)).fetchall()}

    filas = db.execute(config['consulta']).fetchall()
    cursos_filtro, jornadas_filtro = mf.opciones_filtro() if config.get('filtros') else ([], [])
    return render_template('admin/entidad.html', entidad=entidad, config=config, filas=filas,
                           campos=campos, entidades=ENTIDADES, materias_opciones=materias_opciones,
                           seleccionadas=seleccionadas or set(),
                           editando=True, registro_id=registro_id, cursos=cursos_filtro, jornadas=jornadas_filtro)


@admin_bp.route('/<entidad>/<int:registro_id>/eliminar', methods=['POST'])
@requiere_admin
def eliminar(entidad, registro_id):
    config = _config(entidad)
    db = get_db()
    try:
        if entidad == 'matriculas':
            db.execute(SQL_LIMPIAR_CALIFICACION, (registro_id, registro_id))
        db.execute(f'DELETE FROM {config["tabla"]} WHERE id = ?', (registro_id,))
        registrar(db, 'eliminar', f'{config["singular"]} id {registro_id}')
        db.commit()
        flash('Registro eliminado.', 'ok')
    except IntegrityError:
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
            columna = ROLES_CUENTA[rol][2]
            try:
                db.execute(
                    f'INSERT INTO usuarios (correo, contrasena_hash, rol, {columna}) VALUES (?, ?, ?, ?)',
                    (correo, generate_password_hash(contrasena), rol, int(persona_id)))
                registrar(db, 'acceso_creado', f'{rol} {correo}')
                db.commit()
                flash('Acceso creado correctamente.', 'ok')
            except IntegrityError:
                flash('Ese correo ya tiene un acceso, o la persona no existe.', 'error')
        return redirect(url_for('admin.accesos'))

    cuentas = db.execute(
        "SELECT u.id, u.correo, u.rol, "
        "COALESCE(d.nombres || ' ' || d.apellidos, e.nombres || ' ' || e.apellidos, "
        "p.nombres || ' ' || p.apellidos) AS persona "
        "FROM usuarios u "
        "LEFT JOIN docentes d ON d.id = u.docente_id "
        "LEFT JOIN estudiantes e ON e.id = u.estudiante_id "
        "LEFT JOIN personal p ON p.id = u.personal_id "
        "ORDER BY u.rol, persona").fetchall()

    personas = []
    for rol, (tabla, etiqueta, _, filtro) in ROLES_CUENTA.items():
        filas = db.execute(
            f"SELECT id, nombres || ' ' || apellidos AS nombre FROM {tabla} {filtro} ORDER BY apellidos, nombres"
        ).fetchall()
        personas += [(f'{rol}:{fila["id"]}', f'{etiqueta} · {fila["nombre"]}') for fila in filas]

    return render_template('admin/accesos.html', cuentas=cuentas, personas=personas,
                           entidades=ENTIDADES)


@admin_bp.route('/accesos/<int:cuenta_id>/contrasena', methods=['POST'])
@requiere_admin
def restablecer_contrasena(cuenta_id):
    db = get_db()
    nueva = request.form.get('contrasena', '')
    if len(nueva) < 6:
        flash('La contraseña debe tener al menos 6 caracteres.', 'error')
        return redirect(url_for('admin.accesos'))
    cuenta = db.execute('SELECT correo FROM usuarios WHERE id = ?', (cuenta_id,)).fetchone()
    if cuenta is None:
        abort(404)
    db.execute('UPDATE usuarios SET contrasena_hash = ? WHERE id = ?',
               (generate_password_hash(nueva), cuenta_id))
    registrar(db, 'contrasena_restablecida', cuenta['correo'])
    db.commit()
    flash(f'Contraseña restablecida para {cuenta["correo"]}.', 'ok')
    return redirect(url_for('admin.accesos'))


@admin_bp.route('/accesos/<int:cuenta_id>/eliminar', methods=['POST'])
@requiere_admin
def eliminar_acceso(cuenta_id):
    db = get_db()
    db.execute('DELETE FROM usuarios WHERE id = ?', (cuenta_id,))
    registrar(db, 'acceso_eliminado', f'cuenta id {cuenta_id}')
    db.commit()
    flash('Acceso eliminado.', 'ok')
    return redirect(url_for('admin.accesos'))


@admin_bp.route('/aspirantes/<int:aspirante_id>/documentos')
@requiere_admin
def documentos_aspirante(aspirante_id):
    db = get_db()
    aspirante = db.execute(
        "SELECT id, nombres, apellidos, documento, correo, programa, estado, estudiante_id "
        "FROM aspirantes WHERE id = ?",
        (aspirante_id,)).fetchone()
    if aspirante is None:
        abort(404)

    requisitos = db.execute(
        "SELECT r.id AS requisito_id, r.nombre, r.obligatorio, r.seccion, d.id AS documento_id, "
        "d.nombre_original, d.subido_en, d.estado, d.observacion "
        "FROM requisitos r "
        "LEFT JOIN documentos_aspirante d ON d.requisito_id = r.id AND d.aspirante_id = ? "
        "WHERE r.activo = 1 ORDER BY r.id", (aspirante_id,)).fetchall()
    # El certificado de discapacidad solo aplica si el aspirante respondió Sí
    if db.execute('SELECT tiene_discapacidad FROM aspirantes WHERE id = ?', (aspirante_id,)).fetchone()[0] != 'Sí':
        requisitos = [r for r in requisitos if r['nombre'] != 'Certificado de discapacidad']
    cumple = all(fila['estado'] == 'aprobado' for fila in requisitos if fila['obligatorio'])

    return render_template('admin/documentos_aspirante.html', aspirante=aspirante,
                           requisitos=requisitos, cumple=cumple, entidades=ENTIDADES)


@admin_bp.route('/aspirantes/<int:aspirante_id>/documentos/<int:documento_id>/revisar', methods=['POST'])
@requiere_admin
def revisar_documento(aspirante_id, documento_id):
    estado = request.form.get('estado', '')
    observacion = request.form.get('observacion', '').strip()[:500] or None
    if estado not in ('aprobado', 'rechazado'):
        flash('Seleccione si el documento se aprueba o se rechaza.', 'error')
    elif estado == 'rechazado' and not observacion:
        flash('Escriba el motivo del rechazo para que el aspirante lo vea.', 'error')
    else:
        db = get_db()
        cursor = db.execute(
            'UPDATE documentos_aspirante SET estado = ?, observacion = ? WHERE id = ? AND aspirante_id = ?',
            (estado, observacion if estado == 'rechazado' else None, documento_id, aspirante_id))
        if cursor.rowcount:
            registrar(db, 'revision_documento', f'documento id {documento_id} del aspirante id {aspirante_id}: {estado}')
        db.commit()
        if cursor.rowcount:
            flash('Revisión guardada.', 'ok')
        else:
            flash('El documento no existe.', 'error')
    return redirect(url_for('admin.documentos_aspirante', aspirante_id=aspirante_id))


@admin_bp.route('/documentos/<int:documento_id>/descargar')
@requiere_admin
def descargar_documento(documento_id):
    doc = get_db().execute(
        'SELECT nombre_original, nombre_archivo FROM documentos_aspirante WHERE id = ?',
        (documento_id,)).fetchone()
    if doc is None:
        abort(404)
    return send_from_directory(DOCS_DIR, doc['nombre_archivo'], as_attachment=True,
                               download_name=doc['nombre_original'])


@admin_bp.route('/pagos-matricula')
@requiere_admin
def pagos_matricula():
    busqueda = request.args.get('q', '').strip()[:100]
    grupo_id = request.args.get('curso', '')
    jornada_id = request.args.get('jornada', '')
    grupo_id = int(grupo_id) if grupo_id.isdigit() else None
    jornada_id = int(jornada_id) if jornada_id.isdigit() else None
    cursos, jornadas = mf.opciones_filtro()
    return render_template('admin/pagos_matricula.html',
                           registros=mf.estudiantes_con_matricula(busqueda, grupo_id, jornada_id),
                           q=busqueda, modalidades=mf.MODALIDADES, cursos=cursos, jornadas=jornadas,
                           curso_sel=grupo_id, jornada_sel=jornada_id)


@admin_bp.route('/pagos-matricula/<int:recibo_id>/descargar')
@requiere_admin
def descargar_recibo_matricula(recibo_id):
    db = get_db()
    mf.asegurar(db)
    recibo = db.execute('SELECT nombre_original, nombre_archivo FROM recibos_matricula WHERE id = ?',
                        (recibo_id,)).fetchone()
    if recibo is None:
        abort(404)
    return send_from_directory(mf.RECIBOS_DIR, recibo['nombre_archivo'], as_attachment=True,
                               download_name=recibo['nombre_original'])


@admin_bp.route('/pagos-matricula/<int:recibo_id>/revisar', methods=['POST'])
@requiere_admin
def revisar_recibo_matricula(recibo_id):
    observacion = request.form.get('observacion', '').strip()[:500] or None
    ok, mensaje = mf.revisar_recibo(recibo_id, request.form.get('estado', ''), observacion)
    flash(mensaje, 'ok' if ok else 'error')
    return redirect(url_for('admin.pagos_matricula'))


@admin_bp.route('/aspirantes/<int:aspirante_id>/formulario')
@requiere_admin
def formulario_aspirante(aspirante_id):
    from blueprints.aspirante import _datos_aspirante, _requisitos_con_documento

    if get_db().execute('SELECT 1 FROM aspirantes WHERE id = ?', (aspirante_id,)).fetchone() is None:
        abort(404)
    datos = _datos_aspirante(aspirante_id, con_prefill=False)
    documentos = [dict(fila) for fila in _requisitos_con_documento(aspirante_id)]
    pdf = generar_comprobante(datos, datos['hermanos'], documentos)
    return send_file(io.BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
                     download_name='formulario_inscripcion.pdf')


@admin_bp.route('/aspirantes/<int:aspirante_id>/habilitar', methods=['POST'])
@requiere_admin
def habilitar_aspirante(aspirante_id):
    from blueprints.aspirante import _pasos_completos, _requisitos_con_documento

    db = get_db()
    aspirante = db.execute('SELECT * FROM aspirantes WHERE id = ?', (aspirante_id,)).fetchone()
    if aspirante is None:
        abort(404)
    documentos_ok = all(r['estado'] == 'aprobado' for r in _requisitos_con_documento(aspirante_id) if r['obligatorio'])
    if not (documentos_ok and all(_pasos_completos(aspirante_id).values())):
        flash('El aspirante todavía no cumple con los requisitos obligatorios.', 'error')
        return redirect(url_for('admin.documentos_aspirante', aspirante_id=aspirante_id))

    if db.execute("SELECT 1 FROM usuarios WHERE correo = ? AND rol = 'estudiante'",
                  (aspirante['correo'],)).fetchone():
        flash('Este aspirante ya tiene acceso habilitado.', 'error')
        return redirect(url_for('admin.documentos_aspirante', aspirante_id=aspirante_id))
    if db.execute("SELECT 1 FROM usuarios WHERE correo = ? AND rol <> 'estudiante'",
                  (aspirante['correo'],)).fetchone():
        flash('Ese correo ya tiene una cuenta en la plataforma. Use otro correo para el aspirante.', 'error')
        return redirect(url_for('admin.documentos_aspirante', aspirante_id=aspirante_id))

    try:
        # Si el aspirante ya tuvo registro de estudiante, se reutiliza; si no, se vincula o se crea
        estudiante_id = aspirante['estudiante_id']
        existente = None if estudiante_id else db.execute(
            'SELECT id FROM estudiantes WHERE documento = ?', (aspirante['documento'],)).fetchone()
        if estudiante_id:
            mensaje = 'Acceso habilitado de nuevo.'
        elif existente:
            estudiante_id = existente['id']
            mensaje = 'Acceso habilitado. Se vinculó al registro de estudiante que ya existía con ese documento.'
        else:
            cursor = db.execute(
                'INSERT INTO estudiantes (codigo, nombres, apellidos, documento, correo, programa, jornada_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (f'EST{aspirante_id:06d}', aspirante['nombres'], aspirante['apellidos'], aspirante['documento'],
                 aspirante['correo'], aspirante['programa'] or None, aspirante['jornada_id']))
            estudiante_id = cursor.lastrowid
            mensaje = 'Acceso habilitado. El aspirante ya puede entrar a su portal de estudiante.'
        # Los datos de contacto y de familia se copian del aspirante al registro de estudiante
        copia = {c: aspirante[c] for c in ('telefono', 'celular', 'direccion', 'pais', 'departamento', 'ciudad', 'nombre_padre', 'telefono_padre', 'documento_padre', 'nombre_madre', 'telefono_madre', 'documento_madre', 'fecha_nacimiento', 'lugar_expedicion', 'fecha_expedicion', 'estado_civil', 'tipo_sangre', 'tiene_discapacidad', 'discapacidad')}
        db.execute('UPDATE estudiantes SET ' + ', '.join(f'{c} = ?' for c in copia) + ' WHERE id = ?',
                   [copia[c] for c in copia] + [estudiante_id])
        # La cuenta usa el mismo correo y la misma contraseña del aspirante
        db.execute('INSERT INTO usuarios (correo, contrasena_hash, rol, estudiante_id) VALUES (?, ?, ?, ?)',
                   (aspirante['correo'], aspirante['contrasena_hash'], 'estudiante', estudiante_id))
        db.execute("UPDATE aspirantes SET estado = 'habilitado', estudiante_id = ? WHERE id = ?",
                   (estudiante_id, aspirante_id))
        registrar(db, 'aspirante_habilitado', f'aspirante id {aspirante_id} como estudiante id {estudiante_id}')
        db.commit()
    except IntegrityError:
        db.rollback()
        flash('No se pudo habilitar el acceso. Revise que el correo y el documento no estén repetidos.', 'error')
        return redirect(url_for('admin.documentos_aspirante', aspirante_id=aspirante_id))

    flash(mensaje, 'ok')
    return redirect(url_for('admin.documentos_aspirante', aspirante_id=aspirante_id))


@admin_bp.route('/aspirantes/<int:aspirante_id>/deshabilitar', methods=['POST'])
@requiere_admin
def deshabilitar_aspirante(aspirante_id):
    db = get_db()
    aspirante = db.execute('SELECT correo FROM aspirantes WHERE id = ?', (aspirante_id,)).fetchone()
    if aspirante is None:
        abort(404)
    # Quita la cuenta de estudiante y bloquea también el acceso como aspirante
    db.execute("DELETE FROM usuarios WHERE correo = ? AND rol = 'estudiante'", (aspirante['correo'],))
    db.execute("UPDATE aspirantes SET estado = 'deshabilitado' WHERE id = ?", (aspirante_id,))
    registrar(db, 'aspirante_deshabilitado', f'aspirante id {aspirante_id}')
    db.commit()
    flash('Acceso deshabilitado. El aspirante ya no puede entrar a la plataforma.', 'ok')
    return redirect(url_for('admin.entidad', entidad='aspirantes'))


def _documentos_del_docente(docente_id):
    """Lista de documentos del docente: hoja de vida, formación y antecedentes."""
    db = get_db()
    subidos = {fila['tipo']: dict(fila) for fila in db.execute(
        'SELECT tipo, nombre_original, nombre_archivo, subido_en FROM docentes_documentos WHERE docente_id = ?',
        (docente_id,)).fetchall()}
    hoja = db.execute('SELECT nombre_original, nombre_archivo, subido_en FROM hojas_de_vida WHERE docente_id = ?',
                      (docente_id,)).fetchone()
    lista = [{'clave': 'hoja', 'etiqueta': 'Hoja de vida', 'archivo': dict(hoja) if hoja else None}]
    for tipo, (etiqueta, obligatorio) in docs_docente.TIPOS.items():
        lista.append({'clave': tipo, 'etiqueta': etiqueta, 'archivo': subidos.get(tipo)})
    for tipo, (etiqueta, _, obligatorio) in docs_docente.ANTECEDENTES.items():
        lista.append({'clave': tipo, 'etiqueta': etiqueta, 'archivo': subidos.get(tipo)})
    return lista


@admin_bp.route('/docentes/<int:docente_id>/documentos')
@requiere_admin
def documentos_docente(docente_id):
    db = get_db()
    docente = db.execute('SELECT id, nombres, apellidos, documento, correo FROM docentes WHERE id = ?',
                         (docente_id,)).fetchone()
    if docente is None:
        abort(404)
    return render_template('admin/documentos_docente.html', docente=docente,
                           documentos=_documentos_del_docente(docente_id), entidades=ENTIDADES)


@admin_bp.route('/docentes/<int:docente_id>/documentos/<clave>/descargar')
@requiere_admin
def descargar_documento_docente(docente_id, clave):
    db = get_db()
    if clave == 'hoja':
        fila = db.execute('SELECT nombre_original, nombre_archivo FROM hojas_de_vida WHERE docente_id = ?',
                          (docente_id,)).fetchone()
        carpeta = hojas_mod.HOJAS_DIR
    else:
        fila = db.execute('SELECT nombre_original, nombre_archivo FROM docentes_documentos '
                          'WHERE docente_id = ? AND tipo = ?', (docente_id, clave)).fetchone()
        carpeta = docs_docente.DOCS_DIR
    if fila is None:
        abort(404)
    return send_from_directory(carpeta, fila['nombre_archivo'], as_attachment=True,
                               download_name=fila['nombre_original'])
