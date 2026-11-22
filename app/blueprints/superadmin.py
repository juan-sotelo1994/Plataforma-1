import datetime
import os

import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from nucleo.auditoria import asegurar
from nucleo.db import IntegrityError, crear_base
from nucleo.seguridad import requiere_rol
from nucleo.sedes import conectar_central, conectar_sede, correo_en_uso, listar_sedes, nombre_nuevo_esquema


# Vistas de solo lectura de cada sede: (título, encabezados, consulta)
VISTAS_SEDE = {
    'estudiantes': ('Estudiantes', ['Código', 'Nombre', 'Documento', 'Correo', 'Programa', 'Acceso'],
                    "SELECT e.codigo, e.apellidos || ' ' || e.nombres, e.documento, e.correo, e.programa, "
                    "CASE WHEN EXISTS (SELECT 1 FROM usuarios u WHERE u.estudiante_id = e.id) "
                    "THEN 'Habilitado' ELSE 'Sin acceso' END "
                    "FROM estudiantes e ORDER BY e.apellidos, e.nombres"),
    'docentes': ('Docentes', ['Nombres', 'Apellidos', 'Documento', 'Correo', 'Especialidad', 'Acceso'],
                 "SELECT d.nombres, d.apellidos, d.documento, d.correo, d.especialidad, "
                 "CASE WHEN EXISTS (SELECT 1 FROM usuarios u WHERE u.docente_id = d.id) "
                 "THEN 'Habilitado' ELSE 'Sin acceso' END "
                 "FROM docentes d ORDER BY d.apellidos, d.nombres"),
    'cursos': ('Cursos', ['Ciclo', 'Curso', 'Periodo', 'Jornada', 'Materias'],
               "SELECT g.ciclo, g.grupo, g.periodo, j.nombre, "
               "(SELECT COUNT(*) FROM cursos c WHERE c.grupo_id = g.id) "
               "FROM grupos_curso g JOIN jornadas j ON j.id = g.jornada_id "
               "ORDER BY g.periodo DESC, g.ciclo, g.grupo"),
    'aspirantes': ('Aspirantes', ['Nombres', 'Apellidos', 'Documento', 'Correo', 'Estado'],
                   "SELECT nombres, apellidos, documento, correo, estado FROM aspirantes "
                   "ORDER BY apellidos, nombres"),
}
TABLAS_RESUMEN = [('Estudiantes', 'estudiantes'), ('Docentes', 'docentes'), ('Cursos', 'grupos_curso'),
                  ('Aspirantes', 'aspirantes'), ('Cuentas de ingreso', 'usuarios')]


# Horario de cada materia dictada; un curso sin materias aparece con su propio horario
SQL_HORARIOS = """
SELECT * FROM (
    SELECT g.periodo AS periodo, g.grupo AS curso, '—' AS materia, 'Sin materias' AS docente,
           j.nombre AS jornada, COALESCE(g.horario, '—') AS horario
    FROM grupos_curso g
    JOIN jornadas j ON j.id = g.jornada_id
    WHERE NOT EXISTS (SELECT 1 FROM cursos c WHERE c.grupo_id = g.id)
    UNION ALL
    SELECT c.periodo, COALESCE(g.grupo, c.grupo), m.nombre,
           COALESCE(d.nombres || ' ' || d.apellidos, 'Sin docente'), j.nombre,
           COALESCE(c.horario, g.horario, '—')
    FROM cursos c
    JOIN materias m ON m.id = c.materia_id
    JOIN jornadas j ON j.id = c.jornada_id
    LEFT JOIN grupos_curso g ON g.id = c.grupo_id
    LEFT JOIN docentes d ON d.id = c.docente_id
)
ORDER BY periodo DESC, curso, materia
"""

# Cada materia dictada (curso) con sus matriculados, cuántos ya tienen nota y el peso de sus criterios
SQL_AVANCES = """
SELECT c.id, c.periodo, COALESCE(g.grupo, c.grupo) AS curso, m.nombre AS materia,
       COALESCE(d.nombres || ' ' || d.apellidos, 'Sin docente') AS docente,
       (SELECT COUNT(*) FROM matriculas mt WHERE mt.curso_id = c.id) AS matriculados,
       (SELECT COUNT(*) FROM matriculas mt WHERE mt.curso_id = c.id AND EXISTS (
            SELECT 1 FROM calificaciones k WHERE k.curso_id = c.id AND k.estudiante_id = mt.estudiante_id)) AS calificados,
       (SELECT COUNT(*) FROM criterios_evaluacion cr WHERE cr.curso_id = c.id) AS criterios,
       (SELECT COALESCE(SUM(cr.porcentaje), 0) FROM criterios_evaluacion cr WHERE cr.curso_id = c.id) AS criterios_pct
FROM cursos c
JOIN materias m ON m.id = c.materia_id
LEFT JOIN grupos_curso g ON g.id = c.grupo_id
LEFT JOIN docentes d ON d.id = c.docente_id
ORDER BY c.periodo DESC, curso, materia
"""


def _consultar(esquema, sql, parametros=()):
    conexion = conectar_sede(esquema)
    try:
        asegurar(conexion)
        return conexion.execute(sql, parametros).fetchall()
    finally:
        conexion.close()


def _indicadores(esquema):
    """Cifras de una sede para el monitoreo general."""
    cifras = {'estudiantes': 0, 'docentes': 0, 'grupos': 0, 'materias': 0, 'matriculas': 0,
              'calificadas': 0, 'aspirantes': 0, 'ultima': None}
    conexion = conectar_sede(esquema)
    try:
        asegurar(conexion)

        def cuenta(sql):
            return conexion.execute(sql).fetchone()[0]

        cifras.update(
            estudiantes=cuenta('SELECT COUNT(*) FROM estudiantes'),
            docentes=cuenta('SELECT COUNT(*) FROM docentes'),
            grupos=cuenta('SELECT COUNT(*) FROM grupos_curso'),
            materias=cuenta('SELECT COUNT(*) FROM cursos'),
            matriculas=cuenta('SELECT COUNT(*) FROM matriculas'),
            calificadas=cuenta(
                'SELECT COUNT(*) FROM matriculas m WHERE EXISTS (SELECT 1 FROM calificaciones k '
                'WHERE k.curso_id = m.curso_id AND k.estudiante_id = m.estudiante_id)'),
            aspirantes=cuenta('SELECT COUNT(*) FROM aspirantes'),
            ultima=cuenta('SELECT MAX(fecha) FROM auditoria'),
        )
    finally:
        conexion.close()
    return cifras


def _estado_plazo(plazo, hoy):
    if plazo is None:
        return 'Sin plazo'
    if plazo['abre'] and plazo['abre'] > hoy:
        return f'Abre el {plazo["abre"]}'
    if plazo['cierra'] and plazo['cierra'] < hoy:
        return 'Cerrado'
    return 'Abierto'


def _avances(esquema):
    hoy = datetime.date.today().isoformat()
    conexion = conectar_sede(esquema)
    try:
        asegurar(conexion)
        plazos = {fila['periodo']: fila for fila in
                  conexion.execute('SELECT periodo, abre, cierra FROM plazos_notas').fetchall()}
        cursos = conexion.execute(SQL_AVANCES).fetchall()
    finally:
        conexion.close()

    filas = []
    for curso in cursos:
        matriculados, calificados = curso['matriculados'], curso['calificados']
        porcentaje = round(calificados * 100 / matriculados) if matriculados else 0
        if not matriculados:
            estado = 'Sin estudiantes'
        elif not curso['criterios']:
            estado = 'Sin criterios'
        elif calificados == matriculados:
            estado = 'Notas completas'
        else:
            estado = 'En curso'
        filas.append((curso['periodo'], curso['curso'], curso['materia'], curso['docente'], matriculados,
                      calificados, f'{porcentaje} %', f'{curso["criterios_pct"]:g} % en {curso["criterios"]} criterio(s)',
                      _estado_plazo(plazos.get(curso['periodo']), hoy), estado))
    return filas


def _auditoria(esquema, q):
    patron = f'%{q}%'
    return _consultar(
        esquema, "SELECT fecha, usuario, accion, detalle FROM auditoria "
              "WHERE ? = '' OR usuario ILIKE ? OR accion ILIKE ? OR detalle ILIKE ? "
              "ORDER BY id DESC LIMIT 500", (q, patron, patron, patron))


superadmin_bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')


def _panel():
    central = conectar_central()
    try:
        admins = central.execute(
            'SELECT a.id, a.correo, a.sede_id, s.nombre AS sede FROM admins_sede a '
            'JOIN sedes s ON s.id = a.sede_id ORDER BY s.nombre, a.correo').fetchall()
    finally:
        central.close()
    return listar_sedes(), admins


@superadmin_bp.route('/')
@requiere_rol('superadmin')
def inicio():
    sedes, admins = _panel()
    return render_template('superadmin/inicio.html', sedes=sedes, admins=admins)


@superadmin_bp.route('/monitoreo')
@requiere_rol('superadmin')
def monitoreo():
    """Cifras de todas las sedes en una sola tabla."""
    filas = []
    for sede in listar_sedes():
        cifras = _indicadores(sede['archivo'])
        cifras['avance'] = round(cifras['calificadas'] * 100 / cifras['matriculas']) if cifras['matriculas'] else 0
        filas.append({'sede': sede, 'cifras': cifras})
    totales = {clave: sum(f['cifras'][clave] for f in filas)
               for clave in ('estudiantes', 'docentes', 'grupos', 'materias', 'matriculas', 'calificadas', 'aspirantes')}
    totales['avance'] = round(totales['calificadas'] * 100 / totales['matriculas']) if totales['matriculas'] else 0
    return render_template('superadmin/monitoreo.html', filas=filas, totales=totales)


@superadmin_bp.route('/sedes', methods=['POST'])
@requiere_rol('superadmin')
def crear_sede():
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('Escriba el nombre de la sede.', 'error')
        return redirect(url_for('superadmin.inicio'))
    archivo = nombre_nuevo_esquema()
    central = conectar_central()
    try:
        central.execute('INSERT INTO sedes (nombre, archivo) VALUES (?, ?)', (nombre, archivo))
        central.commit()
    except IntegrityError:
        flash('Ya existe una sede con ese nombre.', 'error')
        return redirect(url_for('superadmin.inicio'))
    finally:
        central.close()
    # Cada sede empieza con su propia base, con todas las tablas
    crear_base(archivo)
    flash(f'Sede «{nombre}» creada. Ahora cree su administrador.', 'ok')
    return redirect(url_for('superadmin.inicio'))


@superadmin_bp.route('/sedes/<int:sede_id>')
@requiere_rol('superadmin')
def ver_sede(sede_id):
    """Vista de solo lectura de una sede: su resumen, sus listas y sus administradores."""
    central = conectar_central()
    try:
        sede = central.execute('SELECT id, nombre, archivo FROM sedes WHERE id = ?', (sede_id,)).fetchone()
        administradores = central.execute(
            'SELECT correo FROM admins_sede WHERE sede_id = ? ORDER BY correo', (sede_id,)).fetchall()
    finally:
        central.close()
    if sede is None:
        abort(404)

    esquema = sede['archivo']
    seccion = request.args.get('seccion', 'resumen')
    if seccion == 'resumen':
        conteos = [(titulo, _consultar(esquema, f'SELECT COUNT(*) FROM {tabla}')[0][0])
                   for titulo, tabla in TABLAS_RESUMEN]
        return render_template('superadmin/sede.html', sede=sede, administradores=administradores,
                               seccion=seccion, conteos=conteos, titulo='Resumen', encabezados=[], filas=[])
    q = request.args.get('q', '').strip()
    if seccion == 'horarios':
        titulo, encabezados = 'Horarios', ['Periodo', 'Curso', 'Materia', 'Docente', 'Jornada', 'Horario']
        filas = _consultar(esquema, SQL_HORARIOS)
    elif seccion == 'avances':
        titulo = 'Avances de notas'
        encabezados = ['Periodo', 'Curso', 'Materia', 'Docente', 'Estudiantes', 'Con notas', 'Avance',
                       'Criterios', 'Plazo de notas', 'Estado']
        filas = _avances(esquema)
    elif seccion == 'auditoria':
        titulo, encabezados = 'Auditoría', ['Fecha', 'Usuario', 'Acción', 'Detalle']
        filas = _auditoria(esquema, q)
    elif seccion in VISTAS_SEDE:
        titulo, encabezados, sql = VISTAS_SEDE[seccion]
        filas = _consultar(esquema, sql)
    else:
        abort(404)
    return render_template('superadmin/sede.html', sede=sede, administradores=administradores,
                           seccion=seccion, conteos=[], titulo=titulo, encabezados=encabezados, filas=filas,
                           q=q)


@superadmin_bp.route('/sedes/<int:sede_id>/editar', methods=['POST'])
@requiere_rol('superadmin')
def editar_sede(sede_id):
    """Cambia el nombre de una sede. Sus datos y su base no cambian."""
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('Escriba el nombre de la sede.', 'error')
        return redirect(url_for('superadmin.inicio'))
    central = conectar_central()
    try:
        if central.execute('SELECT 1 FROM sedes WHERE id = ?', (sede_id,)).fetchone() is None:
            abort(404)
        central.execute('UPDATE sedes SET nombre = ? WHERE id = ?', (nombre, sede_id))
        central.commit()
        flash(f'Nombre de la sede actualizado a «{nombre}».', 'ok')
    except IntegrityError:
        flash('Ya existe una sede con ese nombre.', 'error')
    finally:
        central.close()
    return redirect(url_for('superadmin.inicio'))


@superadmin_bp.route('/administradores', methods=['POST'])
@requiere_rol('superadmin')
def crear_administrador():
    correo = request.form.get('correo', '').strip().lower()
    contrasena = request.form.get('contrasena', '')
    sede_id = request.form.get('sede_id', '')
    if '@' not in correo:
        flash('Escriba un correo válido.', 'error')
    elif len(contrasena) < 6:
        flash('La contraseña debe tener al menos 6 caracteres.', 'error')
    elif not sede_id.isdigit():
        flash('Seleccione la sede.', 'error')
    elif correo_en_uso(correo):
        flash('Ese correo ya está en uso en alguna sede.', 'error')
    else:
        central = conectar_central()
        try:
            central.execute('INSERT INTO admins_sede (correo, contrasena_hash, sede_id) VALUES (?, ?, ?)',
                            (correo, generate_password_hash(contrasena), int(sede_id)))
            central.commit()
            flash('Administrador de sede creado.', 'ok')
        except IntegrityError:
            flash('No se pudo crear: revise la sede y el correo.', 'error')
        finally:
            central.close()
    return redirect(url_for('superadmin.inicio'))


@superadmin_bp.route('/administradores/<int:admin_id>/eliminar', methods=['POST'])
@requiere_rol('superadmin')
def eliminar_administrador(admin_id):
    central = conectar_central()
    try:
        if central.execute('DELETE FROM admins_sede WHERE id = ?', (admin_id,)).rowcount == 0:
            abort(404)
        central.commit()
    finally:
        central.close()
    flash('Administrador eliminado. Sus datos de la sede se conservan.', 'ok')
    return redirect(url_for('superadmin.inicio'))
