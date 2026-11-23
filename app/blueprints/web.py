import secrets

import uuid

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from servicios.circulares_data import por_sede
from nucleo.db import IntegrityError, get_db
from nucleo.auditoria import registrar
from nucleo.sedes import conectar_sede, correo_en_uso, listar_sedes
from servicios import google_oauth


web_bp = Blueprint('web', __name__)

# Datos de la institución. Valores de ejemplo: reemplazar por los reales.
EMPRESA = {
    'nombre': 'Plataforma Institucional',
    'lema': 'Actualidad y comunicados',
    'telefono': '(000) 000 0000',
    'telefono_link': '+570000000000',
    'correo': 'contacto@ejemplo.edu.co',
    'oficina': 'Dirección de ejemplo, bloque 1',
    'enlaces_secundarios': [
        {'texto': 'Biblioteca virtual', 'url': '#'},
        {'texto': 'Transparencia', 'url': '#'},
        {'texto': 'Donaciones', 'url': '#'},
        {'texto': 'Plataforma de notas', 'url': '#'},
        {'texto': 'Soy institucional', 'url': '#'},
    ],
    'menu': [
        {'texto': 'Estudia con nosotros', 'url': '#', 'desplegable': True},
        {'texto': 'Cómo formamos', 'url': '#', 'desplegable': True},
        {'texto': 'Programas y proyectos', 'url': '#', 'desplegable': True},
        {'texto': 'El Colegio', 'url': '#', 'desplegable': True},
        {'texto': 'Contáctenos', 'url': '#', 'desplegable': False},
    ],
    'admision': [
        {'texto': 'Proceso de admisión', 'url': '#'},
        {'texto': 'Inscríbete aquí', 'url': '/inscripcion'},
    ],
    'contactos': [
        {'nombre': 'Secretario general', 'cargo': 'Coordinador de calidad',
         'correo': 'secretaria@ejemplo.edu.co'},
        {'nombre': 'Coordinación de sección', 'cargo': 'Preescolar y primaria',
         'correo': 'primaria@ejemplo.edu.co'},
        {'nombre': 'Coordinación de sección', 'cargo': 'Bachillerato',
         'correo': 'bachillerato@ejemplo.edu.co'},
    ],
}

# Requisito que se sube al momento de inscribirse


@web_bp.app_context_processor
def inyectar_empresa():
    # Disponible en todas las plantillas (base del sitio, login, panel)
    return {'empresa': EMPRESA}


@web_bp.route('/')
def inicio():
    # La página de circulares es la principal del sitio
    return render_template('colegio/circulares.html', secciones=por_sede())


CAMPOS_INSCRIPCION = ['nombres', 'apellidos', 'documento', 'correo']


@web_bp.route('/inscripcion', methods=['GET', 'POST'])
def inscripcion():
    if request.method == 'GET':
        return render_template('web/inscripcion.html', datos={})

    # La sede se escoge después, en el formulario de inscripción. Mientras tanto la cuenta queda
    # en la sede principal y, al escoger otra sede, se traslada a la base de esa sede.
    sede = listar_sedes()[0]
    session['sede_archivo'] = sede['archivo']
    session['sede_nombre'] = sede['nombre']
    db = get_db()

    datos = {campo: request.form.get(campo, '').strip() for campo in CAMPOS_INSCRIPCION}
    datos['correo'] = datos['correo'].lower()

    obligatorios = {'nombres': 'Nombres', 'apellidos': 'Apellidos',
                    'correo': 'Correo'}
    faltan = [etiqueta for campo, etiqueta in obligatorios.items() if not datos[campo]]
    if faltan:
        flash('Complete los campos obligatorios: ' + ', '.join(faltan) + '.', 'error')
    elif '@' not in datos['correo']:
        flash('Escriba un correo válido.', 'error')
    elif correo_en_uso(datos['correo']):
        flash('Ese correo ya tiene una cuenta. Inicie sesión o use otro correo.', 'error')
    else:
        try:
            cursor = db.execute(
                'INSERT INTO aspirantes (nombres, apellidos, documento, correo, programa, contrasena_hash, '
                'sede_confirmada) VALUES (?, ?, ?, ?, ?, ?, 0)',
                (datos['nombres'], datos['apellidos'], f'PENDIENTE-{uuid.uuid4().hex[:10]}', datos['correo'],
                 '', generate_password_hash(secrets.token_urlsafe(24))))
            db.commit()
            # La contraseña se crea en la siguiente pantalla; hasta entonces la cuenta no puede entrar
            session['inscripcion_id'] = cursor.lastrowid
        except IntegrityError:
            flash('Ya existe una inscripción con ese documento o correo.', 'error')
        else:
            return redirect(url_for('web.inscripcion_contrasena'))

    return render_template('web/inscripcion.html', datos=datos)


def _buscar_aspirante(correo):
    """Busca la inscripción del correo en todas las sedes. Devuelve (sede, fila) o (None, None)."""
    for sede in listar_sedes():
        conexion = conectar_sede(sede['archivo'])
        try:
            fila = conexion.execute('SELECT id, estado FROM aspirantes WHERE correo = ?', (correo,)).fetchone()
        finally:
            conexion.close()
        if fila:
            return sede, fila
    return None, None


def _iniciar_sesion_aspirante(correo, aspirante_id, sede):
    session.clear()
    session['usuario'] = correo
    session['rol'] = 'aspirante'
    session['persona_id'] = aspirante_id
    session['sede_archivo'], session['sede_nombre'] = sede['archivo'], sede['nombre']
    conexion = conectar_sede(sede['archivo'])
    try:
        registrar(conexion, 'ingreso', 'Inició sesión con Google', usuario=correo)
        conexion.commit()
    finally:
        conexion.close()


def _redirect_uri_google():
    return url_for('web.inscripcion_google_respuesta', _external=True)


@web_bp.route('/inscripcion/google')
def inscripcion_google():
    """Envía al aspirante a Google para escoger la cuenta con la que se inscribe."""
    if not google_oauth.configurado():
        flash('La inscripción con Google no está disponible por ahora. Use el formulario.', 'error')
        return redirect(url_for('web.inscripcion'))
    url, estado = google_oauth.url_autorizacion(_redirect_uri_google())
    session['google_estado'] = estado
    return redirect(url)


@web_bp.route('/inscripcion/google/respuesta')
def inscripcion_google_respuesta():
    """Google regresa aquí. Si el correo ya tiene inscripción, entra; si no, se crea la inscripción."""
    estado = session.pop('google_estado', None)
    if request.args.get('error') or not request.args.get('code'):
        flash('No se completó la inscripción con Google.', 'error')
        return redirect(url_for('web.inscripcion'))
    if not estado or not secrets.compare_digest(estado, request.args.get('state', '')):
        flash('La solicitud de Google no es válida. Intente de nuevo.', 'error')
        return redirect(url_for('web.inscripcion'))
    try:
        datos = google_oauth.datos_usuario(request.args['code'], _redirect_uri_google())
    except google_oauth.ErrorGoogle:
        flash('No fue posible obtener los datos de su cuenta de Google. Intente de nuevo.', 'error')
        return redirect(url_for('web.inscripcion'))

    correo = datos['correo']
    sede, aspirante = _buscar_aspirante(correo)
    if aspirante:
        if aspirante['estado'] == 'deshabilitado':
            flash('Su acceso está deshabilitado. Comuníquese con la institución.', 'error')
            return redirect(url_for('web.inscripcion'))
        _iniciar_sesion_aspirante(correo, aspirante['id'], sede)
        flash('Ya tenía una inscripción con este correo. Continúe donde la dejó.', 'ok')
        return redirect(url_for('aspirante.inicio'))
    if correo_en_uso(correo):
        flash('Ese correo ya tiene una cuenta en la plataforma. Inicie sesión con su contraseña.', 'error')
        return redirect(url_for('autenticar.login'))

    # Como en el formulario: queda en la sede principal hasta que escoja su sede
    sede = listar_sedes()[0]
    conexion = conectar_sede(sede['archivo'])
    try:
        cursor = conexion.execute(
            'INSERT INTO aspirantes (nombres, apellidos, documento, correo, programa, contrasena_hash, '
            'sede_confirmada) VALUES (?, ?, ?, ?, ?, ?, 0)',
            (datos['nombres'] or correo.split('@')[0], datos['apellidos'], f'PENDIENTE-{uuid.uuid4().hex[:10]}',
             correo, '', generate_password_hash(secrets.token_urlsafe(24))))
        conexion.commit()
        aspirante_id = cursor.lastrowid
    except IntegrityError:
        conexion.rollback()
        flash('Ya existe una inscripción con ese correo.', 'error')
        return redirect(url_for('web.inscripcion'))
    finally:
        conexion.close()
    _iniciar_sesion_aspirante(correo, aspirante_id, sede)
    flash('Inscripción creada con su cuenta de Google. Complete sus datos.', 'ok')
    return redirect(url_for('aspirante.inicio'))


@web_bp.route('/inscripcion/contrasena', methods=['GET', 'POST'])
def inscripcion_contrasena():
    """Segundo paso de la inscripción: el aspirante crea y confirma su contraseña."""
    aspirante_id = session.get('inscripcion_id')
    if not aspirante_id:
        flash('Primero diligencie el formulario de inscripción.', 'error')
        return redirect(url_for('web.inscripcion'))
    db = get_db()
    aspirante = db.execute('SELECT nombres, apellidos, correo FROM aspirantes WHERE id = ?',
                           (aspirante_id,)).fetchone()
    if aspirante is None:
        session.pop('inscripcion_id', None)
        return redirect(url_for('web.inscripcion'))

    if request.method == 'POST':
        contrasena = request.form.get('contrasena', '')
        confirmacion = request.form.get('confirmacion', '')
        if len(contrasena) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'error')
        elif contrasena != confirmacion:
            flash('La confirmación de la contraseña no coincide.', 'error')
        else:
            db.execute('UPDATE aspirantes SET contrasena_hash = ? WHERE id = ?',
                       (generate_password_hash(contrasena), aspirante_id))
            db.commit()
            session.pop('inscripcion_id', None)
            flash('Inscripción completa. Inicie sesión con su correo y contraseña para subir sus documentos.', 'ok')
            return redirect(url_for('autenticar.login'))

    return render_template('web/inscripcion_contrasena.html', aspirante=aspirante)


@web_bp.route('/colegio/actualidad/circulares-y-comunicados')
def circulares():
    # Ruta anterior: se redirige a la principal para no dejar enlaces rotos
    return redirect(url_for('web.inicio'), code=301)
