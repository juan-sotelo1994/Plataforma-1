import hmac
import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from nucleo.db import get_db
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


def _autenticar(correo, contrasena):
    """Devuelve (rol, id_de_la_persona) o (None, None) si las credenciales no sirven."""
    if _cuenta_administrador(correo, contrasena):
        return 'admin', None

    fila = get_db().execute(
        'SELECT rol, docente_id, estudiante_id, personal_id, contrasena_hash FROM usuarios WHERE correo = ?',
        (correo,)).fetchone()
    if fila and check_password_hash(fila['contrasena_hash'], contrasena):
        persona_id = {'docente': fila['docente_id'], 'estudiante': fila['estudiante_id']}.get(
            fila['rol'], fila['personal_id'])
        return fila['rol'], persona_id

    # Aspirantes inscritos desde la página pública
    aspirante = get_db().execute(
        'SELECT id, contrasena_hash, estado FROM aspirantes WHERE correo = ?', (correo,)).fetchone()
    if aspirante and check_password_hash(aspirante['contrasena_hash'], contrasena):
        return 'aspirante', aspirante['id']
    return None, None


@autenticar.route('/ingresar', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form.get('correo', '').strip().lower()
        contrasena = request.form.get('contrasena', '')
        rol, persona_id = _autenticar(correo, contrasena)
        if rol:
            session.clear()
            session['usuario'] = correo
            session['rol'] = rol
            session['persona_id'] = persona_id
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
