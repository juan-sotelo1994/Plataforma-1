import hmac
import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from nucleo.auditoria import registrar
from nucleo.sedes import (buscar_administradora_financiera, buscar_financiero, cambiar_contrasena_administradora,
                          cambiar_contrasena_financiero, conectar_central, conectar_sede, listar_sedes,
                          registrar_acceso_financiero)
from nucleo.seguridad import INICIO_POR_ROL, destino_por_rol, requiere_rol


autenticar = Blueprint('autenticar', __name__, url_prefix='/acceso')


# NOTA: la cuenta de administrador vive en .env (DEV_CORREO y DEV_CONTRASENA).
# Docentes y estudiantes tienen cuentas en la tabla "usuarios".

def _cuenta_administrador(correo, contrasena):
    correo_ok = os.environ.get('DEV_CORREO', '').strip().lower()
    clave_ok = os.environ.get('DEV_CONTRASENA', '')
    if not correo_ok or not clave_ok:
        return False
    if not hmac.compare_digest(correo.encode(), correo_ok.encode()):
        return False
    # Si el superadministrador ya cambió su contraseña, vale la nueva; si no, la del .env
    guardada = _hash_superadmin()
    if guardada:
        return check_password_hash(guardada, contrasena)
    return hmac.compare_digest(contrasena.encode(), clave_ok.encode())


def _autenticar_en_sede(esquema, correo, contrasena):
    """Busca al usuario en la base de una sede. Devuelve (rol, id_de_la_persona) o (None, None)."""
    conexion = conectar_sede(esquema)
    try:
        fila = conexion.execute(
            'SELECT rol, docente_id, estudiante_id, personal_id, contrasena_hash FROM usuarios WHERE correo = ?',
            (correo,)).fetchone()
        if fila and check_password_hash(fila['contrasena_hash'], contrasena):
            persona_id = {'docente': fila['docente_id'], 'estudiante': fila['estudiante_id']}.get(
                fila['rol'], fila['personal_id'])
            return fila['rol'], persona_id

        # Aspirantes inscritos desde la página pública
        aspirante = conexion.execute(
            'SELECT id, contrasena_hash FROM aspirantes WHERE correo = ?', (correo,)).fetchone()
        if aspirante and check_password_hash(aspirante['contrasena_hash'], contrasena):
            return 'aspirante', aspirante['id']
        return None, None
    finally:
        conexion.close()


def _autenticar(correo, contrasena):
    """Devuelve (rol, id_de_la_persona, sede) o (None, None, None).

    sede es (archivo, nombre) de la sede a la que entra la persona. El superadministrador no tiene sede.
    """
    if _cuenta_administrador(correo, contrasena):
        return 'superadmin', None, None

    central = conectar_central()
    try:
        admin = central.execute(
            'SELECT a.contrasena_hash, s.archivo, s.nombre FROM admins_sede a '
            'JOIN sedes s ON s.id = a.sede_id WHERE a.correo = ?', (correo,)).fetchone()
    finally:
        central.close()
    if admin and check_password_hash(admin['contrasena_hash'], contrasena):
        return 'admin', None, (admin['archivo'], admin['nombre'])

    # La administradora financiera ve todas las sedes (solo lectura); no entra a una sede en particular
    administradora = buscar_administradora_financiera(correo)
    if administradora and not administradora['bloqueado'] and check_password_hash(administradora['contrasena_hash'], contrasena):
        return 'administradora_financiera', administradora['id'], None

    # El perfil financiero trabaja en la sede que el superadministrador le asignó
    financiero = buscar_financiero(correo)
    if financiero and not financiero['bloqueado'] and check_password_hash(financiero['contrasena_hash'], contrasena):
        if financiero['sede_archivo'] is None:
            return None, None, None
        return 'financiero', financiero['id'], (financiero['sede_archivo'], financiero['sede_nombre'])

    # El correo identifica la sede: se busca en cada base hasta encontrarlo
    for sede in listar_sedes():
        rol, persona_id = _autenticar_en_sede(sede['archivo'], correo, contrasena)
        if rol:
            return rol, persona_id, (sede['archivo'], sede['nombre'])
    return None, None, None


def _registrar_ingreso(archivo, correo):
    conexion = conectar_sede(archivo)
    try:
        registrar(conexion, 'ingreso', 'Inició sesión', usuario=correo)
        conexion.commit()
    finally:
        conexion.close()


@autenticar.route('/ingresar', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form.get('correo', '').strip().lower()
        contrasena = request.form.get('contrasena', '')
        rol, persona_id, sede = _autenticar(correo, contrasena)
        if rol:
            session.clear()
            session['usuario'] = correo
            session['rol'] = rol
            session['persona_id'] = persona_id
            if sede:
                session['sede_archivo'], session['sede_nombre'] = sede
                _registrar_ingreso(sede[0], correo)
            if rol == 'administradora_financiera':
                registrar_acceso_financiero(correo, 'ingreso_administradora', 'Inició sesión en finanzas globales')
            return redirect(destino_por_rol(rol))
        bloqueado = buscar_financiero(correo)
        if bloqueado and bloqueado['bloqueado'] and check_password_hash(bloqueado['contrasena_hash'], contrasena):
            flash('Esta cuenta está bloqueada. Consulte al superadministrador.', 'error')
            return redirect(url_for('autenticar.login'))
        flash('Correo o contraseña incorrectos.', 'error')
        return redirect(url_for('autenticar.login'))
    return render_template('auth/login.html')


@autenticar.route('/salir')
def logout():
    session.clear()
    return redirect(url_for('web.inicio'))


@autenticar.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    return render_template('auth/recuperar.html')


@autenticar.route('/recuperar/codigo', methods=['GET', 'POST'])
def recuperar_codigo():
    return render_template('auth/recuperar_codigo.html',
                           correo_oculto='', restante=0, reenviar_en=0,
                           canal='correo', mensaje=None, errores={})


# Cuentas con contraseña propia: el superadministrador, los administradores de sede y las personas de cada sede
ROLES_CON_CONFIGURACION = ('superadmin', 'admin', 'financiero', 'administradora_financiera', 'docente', 'estudiante',
                           'aspirante', 'administrativo', 'auxiliar')
ETIQUETAS_ROL = {'superadmin': 'Superadministrador', 'admin': 'Administrador de sede', 'financiero': 'Financiero',
                 'administradora_financiera': 'Administradora financiera',
                 'docente': 'Docente', 'estudiante': 'Estudiante', 'aspirante': 'Aspirante',
                 'administrativo': 'Administrativo', 'auxiliar': 'Auxiliar'}


def _hash_superadmin():
    central = conectar_central()
    try:
        fila = central.execute('SELECT contrasena_hash FROM credencial_superadmin WHERE id = 1').fetchone()
    finally:
        central.close()
    return fila['contrasena_hash'] if fila else None


def _hash_vigente(rol, correo):
    """Hash de la contraseña actual. None si el superadministrador todavía usa la del .env."""
    if rol == 'superadmin':
        return _hash_superadmin()
    if rol == 'admin':
        central = conectar_central()
        try:
            fila = central.execute('SELECT contrasena_hash FROM admins_sede WHERE correo = ?', (correo,)).fetchone()
        finally:
            central.close()
        return fila['contrasena_hash'] if fila else None
    if rol == 'financiero':
        fila = buscar_financiero(correo)
        return fila['contrasena_hash'] if fila else None
    if rol == 'administradora_financiera':
        fila = buscar_administradora_financiera(correo)
        return fila['contrasena_hash'] if fila else None
    conexion = conectar_sede(session['sede_archivo'])
    try:
        fila = conexion.execute(
            'SELECT contrasena_hash FROM usuarios WHERE correo = ? '
            'UNION ALL SELECT contrasena_hash FROM aspirantes WHERE correo = ? LIMIT 1',
            (correo, correo)).fetchone()
    finally:
        conexion.close()
    return fila['contrasena_hash'] if fila else None


def _guardar_contrasena(rol, correo, hash_nuevo):
    if rol == 'superadmin':
        central = conectar_central()
        try:
            central.execute(
                'INSERT INTO credencial_superadmin (id, contrasena_hash) VALUES (1, ?) '
                'ON CONFLICT (id) DO UPDATE SET contrasena_hash = excluded.contrasena_hash', (hash_nuevo,))
            central.commit()
        finally:
            central.close()
    elif rol == 'admin':
        central = conectar_central()
        try:
            central.execute('UPDATE admins_sede SET contrasena_hash = ? WHERE correo = ?', (hash_nuevo, correo))
            central.commit()
        finally:
            central.close()
    elif rol == 'financiero':
        cambiar_contrasena_financiero(correo, hash_nuevo)
    elif rol == 'administradora_financiera':
        cambiar_contrasena_administradora(correo, hash_nuevo)
    else:
        # La misma contraseña queda en la cuenta de ingreso y en la ficha de aspirante, si la hay
        conexion = conectar_sede(session['sede_archivo'])
        try:
            conexion.execute('UPDATE usuarios SET contrasena_hash = ? WHERE correo = ?', (hash_nuevo, correo))
            conexion.execute('UPDATE aspirantes SET contrasena_hash = ? WHERE correo = ?', (hash_nuevo, correo))
            registrar(conexion, 'contrasena_cambiada', 'Cambió su contraseña', usuario=correo)
            conexion.commit()
        finally:
            conexion.close()


def _contrasena_actual_ok(rol, correo, actual):
    guardada = _hash_vigente(rol, correo)
    if guardada is None:
        # Superadministrador sin cambios: vale la clave del .env
        return _cuenta_administrador(correo, actual)
    return check_password_hash(guardada, actual)


def _base_configuracion(rol):
    """Cada perfil muestra la página dentro de su propio menú; los demás usan el menú común."""
    if rol == 'admin':
        return 'admin/base_admin.html'
    if rol == 'docente':
        return 'docente/base_docente.html'
    if rol == 'estudiante':
        return 'panel/base_panel.html'
    return 'auth/base_configuracion.html'


@autenticar.route('/configuracion', methods=['GET', 'POST'])
@requiere_rol(*ROLES_CON_CONFIGURACION)
def configuracion():
    rol = session['rol']
    correo = session['usuario']
    if request.method == 'POST':
        actual = request.form.get('actual', '')
        nueva = request.form.get('nueva', '')
        confirmacion = request.form.get('confirmacion', '')
        if not _contrasena_actual_ok(rol, correo, actual):
            flash('La contraseña actual no es correcta.', 'error')
        elif len(nueva) < 6:
            flash('La nueva contraseña debe tener al menos 6 caracteres.', 'error')
        elif nueva != confirmacion:
            flash('La confirmación no coincide con la nueva contraseña.', 'error')
        elif nueva == actual:
            flash('La nueva contraseña debe ser distinta de la actual.', 'error')
        else:
            _guardar_contrasena(rol, correo, generate_password_hash(nueva))
            flash('Su contraseña fue actualizada. Desde ahora ingrese con la nueva.', 'ok')
            return redirect(url_for('autenticar.configuracion'))

    extra = {}
    if rol == 'estudiante':
        # El menú del estudiante necesita sus datos y los grupos del menú
        from blueprints.dash import MENU_GRUPOS, _datos_estudiante
        extra = {'usuario': _datos_estudiante(session['persona_id']), 'grupos': MENU_GRUPOS}
    return render_template('auth/configuracion.html', base=_base_configuracion(rol), rol=rol,
                           etiqueta_rol=ETIQUETAS_ROL[rol], correo=correo,
                           inicio=url_for(INICIO_POR_ROL[rol]), **extra)
