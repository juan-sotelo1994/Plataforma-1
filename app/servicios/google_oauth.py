"""Inicio de sesión con Google (OAuth 2.0 / OpenID Connect), solo con la biblioteca estándar.

Necesita GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en app/.env. En la consola de Google Cloud, el
cliente OAuth (tipo "Aplicación web") debe tener como URI de redirección autorizado la ruta
/inscripcion/google/respuesta del sitio, por ejemplo http://127.0.0.1:5712/inscripcion/google/respuesta
"""
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request


URL_AUTORIZACION = 'https://accounts.google.com/o/oauth2/v2/auth'
URL_TOKEN = 'https://oauth2.googleapis.com/token'
URL_USUARIO = 'https://openidconnect.googleapis.com/v1/userinfo'


class ErrorGoogle(Exception):
    pass


def configurado():
    return bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))


def url_autorizacion(redirect_uri):
    """Devuelve (url a la que se envía al usuario, estado anti-CSRF que se guarda en la sesión)."""
    estado = secrets.token_urlsafe(24)
    parametros = {
        'client_id': os.environ['GOOGLE_CLIENT_ID'],
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': estado,
        'prompt': 'select_account',
    }
    return f'{URL_AUTORIZACION}?{urllib.parse.urlencode(parametros)}', estado


def _pedir_json(peticion):
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            return json.loads(respuesta.read().decode('utf-8'))
    except (urllib.error.URLError, ValueError) as error:
        raise ErrorGoogle(str(error)) from error


def datos_usuario(codigo, redirect_uri):
    """Cambia el código de Google por los datos de la cuenta: correo, nombres y apellidos."""
    cuerpo = urllib.parse.urlencode({
        'code': codigo,
        'client_id': os.environ['GOOGLE_CLIENT_ID'],
        'client_secret': os.environ['GOOGLE_CLIENT_SECRET'],
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }).encode()
    token = _pedir_json(urllib.request.Request(URL_TOKEN, data=cuerpo, method='POST'))
    if 'access_token' not in token:
        raise ErrorGoogle('Google no entregó el token de acceso.')
    usuario = _pedir_json(urllib.request.Request(
        URL_USUARIO, headers={'Authorization': f'Bearer {token["access_token"]}'}))
    if not usuario.get('email') or not usuario.get('email_verified'):
        raise ErrorGoogle('La cuenta de Google no tiene un correo verificado.')
    return {
        'correo': usuario['email'].strip().lower(),
        'nombres': (usuario.get('given_name') or usuario.get('name') or '').strip(),
        'apellidos': (usuario.get('family_name') or '').strip(),
    }
