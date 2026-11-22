"""Perfil financiero: cuentas, movimientos, kárdex y bajas de cada sede, por separado de lo académico."""
import datetime
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from nucleo.db import IntegrityError
from nucleo.seguridad import requiere_rol
from nucleo.sedes import buscar_financiero_por_id, conectar_sede, listar_sedes
from servicios import finanzas


finanzas_bp = Blueprint('finanzas', __name__, url_prefix='/finanzas')


@finanzas_bp.before_request
def cuenta_habilitada():
    """Si el usuario fue bloqueado o quitado mientras tenía sesión, la sesión se cierra en su siguiente acción."""
    if session.get('rol') != 'financiero':
        return None
    usuario = buscar_financiero_por_id(session.get('persona_id')) if session.get('persona_id') else None
    # El id del usuario financiero va en persona_id al ingresar (ver auth._autenticar)
    if usuario is None or usuario['bloqueado']:
        session.clear()
        flash('Su acceso financiero está deshabilitado. Consulte al superadministrador.', 'error')
        return redirect(url_for('autenticar.login'))
    return None

SECCIONES = {
    'resumen': 'Resumen',
    'movimientos': 'Movimientos',
    'cuentas': 'Cuentas',
    'kardex': 'Kárdex',
    'bajas': 'Bajas',
}


@finanzas_bp.app_template_filter('pesos')
def pesos(valor, decimales=0):
    """Cifra en pesos colombianos: $ 1.234.567 (o con centavos)."""
    numero = Decimal(valor or 0)
    texto = f'{numero:,.{decimales}f}'
    return '$ ' + texto.replace(',', 'X').replace('.', ',').replace('X', '.')


def _sede_o_404(sede_id):
    for sede in listar_sedes():
        if sede['id'] == sede_id:
            return sede
    abort(404)


def _abrir(sede_id):
    """La sede pedida y su conexión, con las tablas de finanzas listas. Solo la sede asignada a la persona."""
    sede = _sede_o_404(sede_id)
    if sede['archivo'] != session.get('sede_archivo'):
        abort(403)
    conexion = conectar_sede(sede['archivo'])
    finanzas.asegurar(conexion)
    return sede, conexion


def _ir_a(sede_id, seccion):
    return redirect(url_for('finanzas.sede', sede_id=sede_id, seccion=seccion))


def _ejecutar(sede_id, seccion, accion, mensaje_ok, *argumentos):
    """Corre una acción de finanzas: confirma si sale bien y muestra el motivo si no."""
    _, conexion = _abrir(sede_id)
    try:
        accion(conexion, *argumentos)
        conexion.commit()
        flash(mensaje_ok, 'ok')
    except ValueError as error:
        conexion.rollback()
        flash(str(error), 'error')
    except IntegrityError:
        conexion.rollback()
        flash('Ya existe un registro con esos datos.', 'error')
    finally:
        conexion.close()
    return _ir_a(sede_id, seccion)


@finanzas_bp.route('/')
@requiere_rol('financiero')
def inicio():
    """Cada persona financiera entra directo a la sede que le fue asignada."""
    for sede in listar_sedes():
        if sede['archivo'] == session.get('sede_archivo'):
            return redirect(url_for('finanzas.sede', sede_id=sede['id']))
    abort(403)


@finanzas_bp.route('/<int:sede_id>')
@finanzas_bp.route('/<int:sede_id>/<seccion>')
@requiere_rol('financiero')
def sede(sede_id, seccion='resumen'):
    if seccion not in SECCIONES:
        abort(404)
    sede_actual, conexion = _abrir(sede_id)
    contexto = {}
    try:
        if seccion == 'resumen':
            contexto['resumen'] = finanzas.resumen(conexion)
            contexto['cuentas'] = finanzas.cuentas_con_totales(conexion)
        elif seccion == 'movimientos':
            filtros = {'tipo': request.args.get('tipo', ''), 'cuenta': request.args.get('cuenta', ''),
                       'desde': request.args.get('desde', ''), 'hasta': request.args.get('hasta', ''),
                       'anulados': request.args.get('anulados', '')}
            contexto['filtros'] = filtros
            contexto['movimientos'] = finanzas.listar_movimientos(
                conexion, tipo=filtros['tipo'], cuenta_id=filtros['cuenta'], desde=filtros['desde'],
                hasta=filtros['hasta'], incluir_anulados=filtros['anulados'] == '1')
            contexto['cuentas'] = finanzas.listar_cuentas(conexion, solo_activas=True)
        elif seccion == 'cuentas':
            contexto['cuentas'] = finanzas.cuentas_con_totales(conexion)
        elif seccion == 'kardex':
            contexto['articulos'] = finanzas.listar_articulos(conexion)
            seleccionado = request.args.get('articulo', '')
            if seleccionado.isdigit():
                contexto['seleccionado'] = int(seleccionado)
                contexto['lineas'] = finanzas.kardex_articulo(conexion, int(seleccionado))
        elif seccion == 'bajas':
            contexto['bajas'] = finanzas.listar_bajas(conexion)
            contexto['articulos'] = finanzas.listar_articulos(conexion)
    finally:
        conexion.close()
    return render_template('finanzas/sede.html', sede=sede_actual, seccion=seccion, secciones=SECCIONES,
                           hoy=datetime.date.today().isoformat(), **contexto)


@finanzas_bp.route('/<int:sede_id>/cuentas', methods=['POST'])
@requiere_rol('financiero')
def crear_cuenta(sede_id):
    return _ejecutar(sede_id, 'cuentas', lambda c: finanzas.crear_cuenta(
        c, request.form.get('tipo', ''), request.form.get('nombre', ''), session['usuario']),
        'Cuenta creada.')


@finanzas_bp.route('/<int:sede_id>/cuentas/<int:cuenta_id>/estado', methods=['POST'])
@requiere_rol('financiero')
def cambiar_estado_cuenta(sede_id, cuenta_id):
    return _ejecutar(sede_id, 'cuentas', lambda c: finanzas.cambiar_estado_cuenta(c, cuenta_id, session['usuario']),
                     'Estado de la cuenta actualizado.')


@finanzas_bp.route('/<int:sede_id>/movimientos', methods=['POST'])
@requiere_rol('financiero')
def crear_movimiento(sede_id):
    f = request.form
    return _ejecutar(sede_id, 'movimientos', lambda c: finanzas.registrar_movimiento(
        c, f.get('fecha', ''), f.get('tipo', ''), f.get('cuenta_id', ''), f.get('monto', ''),
        f.get('concepto', ''), f.get('referencia', ''), session['usuario']),
        'Movimiento registrado.')


@finanzas_bp.route('/<int:sede_id>/movimientos/<int:movimiento_id>/anular', methods=['POST'])
@requiere_rol('financiero')
def anular_movimiento(sede_id, movimiento_id):
    return _ejecutar(sede_id, 'movimientos', lambda c: finanzas.anular_movimiento(
        c, movimiento_id, request.form.get('motivo', ''), session['usuario']),
        'Movimiento anulado. Queda registrado en la auditoría.')


@finanzas_bp.route('/<int:sede_id>/kardex/articulos', methods=['POST'])
@requiere_rol('financiero')
def crear_articulo(sede_id):
    f = request.form
    return _ejecutar(sede_id, 'kardex', lambda c: finanzas.crear_articulo(
        c, f.get('codigo', ''), f.get('nombre', ''), f.get('unidad', ''), session['usuario']),
        'Artículo creado.')


@finanzas_bp.route('/<int:sede_id>/kardex/entrada', methods=['POST'])
@requiere_rol('financiero')
def registrar_entrada(sede_id):
    f = request.form
    return _ejecutar(sede_id, 'kardex', lambda c: finanzas.registrar_entrada(
        c, f.get('articulo_id', ''), f.get('fecha', ''), f.get('cantidad', ''), f.get('costo_unitario', ''),
        f.get('detalle', ''), session['usuario']),
        'Entrada registrada en el kárdex.')


@finanzas_bp.route('/<int:sede_id>/bajas', methods=['POST'])
@requiere_rol('financiero')
def registrar_baja(sede_id):
    f = request.form
    return _ejecutar(sede_id, 'bajas', lambda c: finanzas.registrar_baja(
        c, f.get('articulo_id', ''), f.get('fecha', ''), f.get('cantidad', ''), f.get('motivo', ''),
        session['usuario']),
        'Baja registrada. Se descontó del kárdex.')
