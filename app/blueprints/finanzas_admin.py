"""Administradora financiera: ve las cuentas de los financieros y las finanzas de todas las sedes.

Es solo de lectura. Cada consulta queda en la bitácora de accesos, que el superadministrador revisa.
"""
from flask import Blueprint, abort, flash, redirect, render_template, session, url_for

from nucleo.seguridad import requiere_rol
from nucleo.sedes import (buscar_administradora_por_id, conectar_sede, listar_financieros, listar_sedes,
                          registrar_acceso_financiero)
from servicios import finanzas


finanzas_admin_bp = Blueprint('finanzas_admin', __name__, url_prefix='/finanzas-admin')
ROL = 'administradora_financiera'


@finanzas_admin_bp.before_request
def cuenta_habilitada():
    """Si la administradora fue bloqueada o quitada mientras tenía sesión, la sesión se cierra."""
    if session.get('rol') != ROL:
        return None
    admin = buscar_administradora_por_id(session.get('persona_id')) if session.get('persona_id') else None
    if admin is None or admin['bloqueado']:
        session.clear()
        flash('Su acceso está deshabilitado. Consulte al superadministrador.', 'error')
        return redirect(url_for('autenticar.login'))
    return None


@finanzas_admin_bp.route('/')
@requiere_rol(ROL)
def inicio():
    saldos = []
    for sede in listar_sedes():
        conexion = conectar_sede(sede['archivo'])
        try:
            finanzas.asegurar(conexion)
            saldos.append({'sede': sede, 'resumen': finanzas.resumen(conexion)})
        finally:
            conexion.close()
    return render_template('finanzas_admin/inicio.html', saldos=saldos, usuarios=listar_financieros(),
                           indicadores=finanzas.indicadores_globales())


@finanzas_admin_bp.route('/sede/<int:sede_id>')
@finanzas_admin_bp.route('/sede/<int:sede_id>/<seccion>')
@requiere_rol(ROL)
def sede(sede_id, seccion='resumen'):
    sede_actual = next((s for s in listar_sedes() if s['id'] == sede_id), None)
    if sede_actual is None or seccion not in finanzas.SECCIONES_SEDE:
        abort(404)
    registrar_acceso_financiero(session['usuario'], 'consulta_sede',
                                f'Consultó {sede_actual["nombre"]} · {finanzas.SECCIONES_SEDE[seccion]}')
    conexion = conectar_sede(sede_actual['archivo'])
    try:
        contexto = finanzas.datos_vista_sede(conexion, seccion)
    finally:
        conexion.close()
    return render_template('finanzas_admin/sede.html', sede=sede_actual, seccion=seccion,
                           secciones=finanzas.SECCIONES_SEDE, **contexto)
