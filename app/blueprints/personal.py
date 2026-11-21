from flask import Blueprint, abort, render_template, session

from nucleo.db import get_db
from nucleo.seguridad import requiere_rol


personal_bp = Blueprint('personal', __name__, url_prefix='/personal')

ETIQUETA_TIPO = {'administrativo': 'Administrativo', 'auxiliar': 'Auxiliar'}


@personal_bp.route('/')
@requiere_rol('administrativo', 'auxiliar')
def inicio():
    persona = get_db().execute(
        'SELECT nombres, apellidos, documento, correo, tipo FROM personal WHERE id = ?',
        (session['persona_id'],)).fetchone()
    if persona is None:
        abort(404)
    return render_template('personal/inicio.html', persona=persona,
                           cargo=ETIQUETA_TIPO.get(persona['tipo'], persona['tipo']))
