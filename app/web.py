from flask import Blueprint, redirect, render_template, url_for

from circulares_data import por_sede


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
        {'texto': 'Inscríbete aquí', 'url': '#'},
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

@web_bp.app_context_processor
def inyectar_empresa():
    # Disponible en todas las plantillas (base del sitio, login, panel)
    return {'empresa': EMPRESA}


@web_bp.route('/')
def inicio():
    # La página de circulares es la principal del sitio
    return render_template('colegio/circulares.html', secciones=por_sede())


@web_bp.route('/colegio/actualidad/circulares-y-comunicados')
def circulares():
    # Ruta anterior: se redirige a la principal para no dejar enlaces rotos
    return redirect(url_for('web.inicio'), code=301)
