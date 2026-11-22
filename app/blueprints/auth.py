import hmac
import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from nucleo.auditoria import registrar
from nucleo.sedes import RUTA_CENTRAL, conectar, listar_sedes, ruta_sede
from nucleo.seguridad import destino_por_rol


autenticar = Blueprint('autenticar', __name__, url_prefix='/acceso')


# NOTA: la cuenta de administrador vive en .env (DEV_CORREO y DEV_CONTRASENA).
# Docentes y estudiantes tienen cuentas en la tabla "usuarios".

def _cuenta_administrador(correo, contrasena):
    correo_ok = os.environ.get('DEV_CORREO', '').strip().lower()
    clave_ok = os.environ.get('DEV_CONTRASENA', '')
    if not correo_ok or not clave_ok:
        return False
    return (hmac.compare_digest(correo.encode(), correo_ok.encode())
            and hmac.compare_digest(contrasena.encode(), clave_ok.encode()))


def _autenticar_en_sede(ruta, correo, contrasena):
    """Busca al usuario en la base de una sede. Devuelve (rol, id_de_la_persona) o (None, None)."""
    conexion = conectar(ruta)
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

    central = conectar(RUTA_CENTRAL)
    try:
        admin = central.execute(
            'SELECT a.contrasena_hash, s.archivo, s.nombre FROM admins_sede a '
            'JOIN sedes s ON s.id = a.sede_id WHERE a.correo = ?', (correo,)).fetchone()
    finally:
        central.close()
    if admin and check_password_hash(admin['contrasena_hash'], contrasena):
        return 'admin', None, (admin['archivo'], admin['nombre'])

    # El correo identifica la sede: se busca en cada base hasta encontrarlo
    for sede in listar_sedes():
        ruta = ruta_sede(sede['archivo'])
        if not os.path.exists(ruta):
            continue
        rol, persona_id = _autenticar_en_sede(ruta, correo, contrasena)
        if rol:
            return rol, persona_id, (sede['archivo'], sede['nombre'])
    return None, None, None


def _registrar_ingreso(archivo, correo):
    conexion = conectar(ruta_sede(archivo))
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
            return redirect(destino_por_rol(rol))
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
