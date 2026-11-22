import sqlite3
import uuid

import os

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from nucleo.db import crear_base
from nucleo.seguridad import requiere_rol
from nucleo.sedes import RUTA_CENTRAL, conectar, correo_en_uso, listar_sedes, ruta_sede


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


def _consultar(ruta, sql):
    if not os.path.exists(ruta):
        return []
    conexion = conectar(ruta)
    try:
        return conexion.execute(sql).fetchall()
    finally:
        conexion.close()


superadmin_bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')


def _panel():
    central = conectar(RUTA_CENTRAL)
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


@superadmin_bp.route('/sedes', methods=['POST'])
@requiere_rol('superadmin')
def crear_sede():
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('Escriba el nombre de la sede.', 'error')
        return redirect(url_for('superadmin.inicio'))
    archivo = f'sede_{uuid.uuid4().hex[:10]}.db'
    central = conectar(RUTA_CENTRAL)
    try:
        central.execute('INSERT INTO sedes (nombre, archivo) VALUES (?, ?)', (nombre, archivo))
        central.commit()
    except sqlite3.IntegrityError:
        flash('Ya existe una sede con ese nombre.', 'error')
        return redirect(url_for('superadmin.inicio'))
    finally:
        central.close()
    # Cada sede empieza con su propia base, con todas las tablas
    crear_base(ruta_sede(archivo))
    flash(f'Sede «{nombre}» creada. Ahora cree su administrador.', 'ok')
    return redirect(url_for('superadmin.inicio'))


@superadmin_bp.route('/sedes/<int:sede_id>')
@requiere_rol('superadmin')
def ver_sede(sede_id):
    """Vista de solo lectura de una sede: su resumen, sus listas y sus administradores."""
    central = conectar(RUTA_CENTRAL)
    try:
        sede = central.execute('SELECT id, nombre, archivo FROM sedes WHERE id = ?', (sede_id,)).fetchone()
        administradores = central.execute(
            'SELECT correo FROM admins_sede WHERE sede_id = ? ORDER BY correo', (sede_id,)).fetchall()
    finally:
        central.close()
    if sede is None:
        abort(404)

    ruta = ruta_sede(sede['archivo'])
    seccion = request.args.get('seccion', 'resumen')
    if seccion == 'resumen':
        conteos = [(titulo, _consultar(ruta, f'SELECT COUNT(*) FROM {tabla}')[0][0]
                    if os.path.exists(ruta) else 0)
                   for titulo, tabla in TABLAS_RESUMEN]
        return render_template('superadmin/sede.html', sede=sede, administradores=administradores,
                               seccion=seccion, conteos=conteos, titulo='Resumen', encabezados=[], filas=[])
    if seccion not in VISTAS_SEDE:
        abort(404)
    titulo, encabezados, sql = VISTAS_SEDE[seccion]
    filas = _consultar(ruta, sql)
    return render_template('superadmin/sede.html', sede=sede, administradores=administradores,
                           seccion=seccion, conteos=[], titulo=titulo, encabezados=encabezados, filas=filas)


@superadmin_bp.route('/sedes/<int:sede_id>/editar', methods=['POST'])
@requiere_rol('superadmin')
def editar_sede(sede_id):
    """Cambia el nombre de una sede. Sus datos y su base no cambian."""
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('Escriba el nombre de la sede.', 'error')
        return redirect(url_for('superadmin.inicio'))
    central = conectar(RUTA_CENTRAL)
    try:
        if central.execute('SELECT 1 FROM sedes WHERE id = ?', (sede_id,)).fetchone() is None:
            abort(404)
        central.execute('UPDATE sedes SET nombre = ? WHERE id = ?', (nombre, sede_id))
        central.commit()
        flash(f'Nombre de la sede actualizado a «{nombre}».', 'ok')
    except sqlite3.IntegrityError:
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
        central = conectar(RUTA_CENTRAL)
        try:
            central.execute('INSERT INTO admins_sede (correo, contrasena_hash, sede_id) VALUES (?, ?, ?)',
                            (correo, generate_password_hash(contrasena), int(sede_id)))
            central.commit()
            flash('Administrador de sede creado.', 'ok')
        except sqlite3.IntegrityError:
            flash('No se pudo crear: revise la sede y el correo.', 'error')
        finally:
            central.close()
    return redirect(url_for('superadmin.inicio'))


@superadmin_bp.route('/administradores/<int:admin_id>/eliminar', methods=['POST'])
@requiere_rol('superadmin')
def eliminar_administrador(admin_id):
    central = conectar(RUTA_CENTRAL)
    try:
        if central.execute('DELETE FROM admins_sede WHERE id = ?', (admin_id,)).rowcount == 0:
            abort(404)
        central.commit()
    finally:
        central.close()
    flash('Administrador eliminado. Sus datos de la sede se conservan.', 'ok')
    return redirect(url_for('superadmin.inicio'))
