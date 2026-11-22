import secrets

import uuid

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from servicios.circulares_data import por_sede
from nucleo.db import IntegrityError, get_db
from nucleo.sedes import correo_en_uso, listar_sedes


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
    sedes = listar_sedes()
    if request.method == 'GET':
        return render_template('web/inscripcion.html', datos={}, sedes=sedes)

    # La inscripción se guarda en la base de la sede que escoge el aspirante
    sede = next((s for s in sedes if str(s['id']) == request.form.get('sede_id', '')), None)
    if sede is None:
        flash('Seleccione la sede a la que se inscribe.', 'error')
        return render_template('web/inscripcion.html', datos={}, sedes=sedes)
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
                'INSERT INTO aspirantes (nombres, apellidos, documento, correo, programa, contrasena_hash) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (datos['nombres'], datos['apellidos'], f'PENDIENTE-{uuid.uuid4().hex[:10]}', datos['correo'],
                 '', generate_password_hash(secrets.token_urlsafe(24))))
            db.commit()
            # La contraseña se crea en la siguiente pantalla; hasta entonces la cuenta no puede entrar
            session['inscripcion_id'] = cursor.lastrowid
        except IntegrityError:
            flash('Ya existe una inscripción con ese documento o correo.', 'error')
        else:
            return redirect(url_for('web.inscripcion_contrasena'))

    return render_template('web/inscripcion.html', datos=datos, sedes=sedes)


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
