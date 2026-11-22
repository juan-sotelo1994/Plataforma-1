from flask import Flask, render_template, request
from dotenv import load_dotenv
import os


# Variables secretas desde el archivo .env (no se sube a GitHub)
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # subidas de archivos (contratos en PDF)


# resgistro de las importaciones y configuraciones
from blueprints.auth import autenticar
from blueprints.dash import dashboard_bp
from blueprints.web import web_bp
from blueprints.api import api_bp
from blueprints.admin import admin_bp
from blueprints.docente import docente_bp
from blueprints.aspirante import aspirante_bp
from blueprints.datos_docente import datos_docente_bp
from blueprints.personal import personal_bp
from blueprints.superadmin import superadmin_bp
from blueprints.finanzas import finanzas_bp
from blueprints.finanzas_admin import finanzas_admin_bp
from nucleo.db import init_app as iniciar_base_de_datos


# Registro de blueprints
app.register_blueprint(web_bp)
app.register_blueprint(autenticar)
app.register_blueprint(dashboard_bp)
app.register_blueprint(api_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(docente_bp)
app.register_blueprint(aspirante_bp)
app.register_blueprint(datos_docente_bp)
app.register_blueprint(personal_bp)
app.register_blueprint(superadmin_bp)
app.register_blueprint(finanzas_bp)
app.register_blueprint(finanzas_admin_bp)

# Crea las tablas de la base de datos si todavía no existen
iniciar_base_de_datos(app)


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '1') == '1',
            host=os.environ.get('HOST', '127.0.0.1'), port=5712)
