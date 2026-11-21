import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from servicios.circulares_data import por_sede
from nucleo.db import get_db
from servicios.documentos import guardar_documento


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
REQUISITO_IDENTIDAD = 'Documento de identidad del aspirante'


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
    db = get_db()

    if request.method == 'GET':
        return render_template('web/inscripcion.html', datos={})

    datos = {campo: request.form.get(campo, '').strip() for campo in CAMPOS_INSCRIPCION}
    datos['correo'] = datos['correo'].lower()
    contrasena = request.form.get('contrasena', '')
    confirmacion = request.form.get('confirmacion', '')
    archivo = request.files.get('documento_identidad')

    obligatorios = {'nombres': 'Nombres', 'apellidos': 'Apellidos', 'documento': 'Número de documento',
                    'correo': 'Correo'}
    faltan = [etiqueta for campo, etiqueta in obligatorios.items() if not datos[campo]]
    if faltan:
        flash('Complete los campos obligatorios: ' + ', '.join(faltan) + '.', 'error')
    elif archivo is None or not archivo.filename:
        flash('Cargue el escaneado de su documento de identidad.', 'error')
    elif '@' not in datos['correo']:
        flash('Escriba un correo válido.', 'error')
    elif len(contrasena) < 6:
        flash('La contraseña debe tener al menos 6 caracteres.', 'error')
    elif contrasena != confirmacion:
        flash('La confirmación de la contraseña no coincide.', 'error')
    elif db.execute('SELECT 1 FROM usuarios WHERE correo = ?', (datos['correo'],)).fetchone():
        flash('Ese correo ya tiene una cuenta. Inicie sesión o use otro correo.', 'error')
    else:
        try:
            cursor = db.execute(
                'INSERT INTO aspirantes (nombres, apellidos, documento, correo, programa, contrasena_hash) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (datos['nombres'], datos['apellidos'], datos['documento'], datos['correo'],
                 '', generate_password_hash(contrasena)))
            db.commit()
            aspirante_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            flash('Ya existe una inscripción con ese documento o correo.', 'error')
        else:
            requisito = db.execute('SELECT id FROM requisitos WHERE nombre = ?', (REQUISITO_IDENTIDAD,)).fetchone()
            ok, mensaje = (guardar_documento(aspirante_id, requisito['id'], archivo)
                           if requisito else (False, 'El requisito de documento de identidad no está configurado.'))
            if not ok:
                # Si el documento no sirve, no se crea la inscripción a medias
                db.execute('DELETE FROM aspirantes WHERE id = ?', (aspirante_id,))
                db.commit()
                flash(f'La inscripción no se guardó: {mensaje}', 'error')
            else:
                flash('Inscripción recibida. Inicie sesión con su correo y contraseña para completar sus documentos.', 'ok')
                return redirect(url_for('autenticar.login'))

    return render_template('web/inscripcion.html', datos=datos)


@web_bp.route('/colegio/actualidad/circulares-y-comunicados')
def circulares():
    # Ruta anterior: se redirige a la principal para no dejar enlaces rotos
    return redirect(url_for('web.inicio'), code=301)
