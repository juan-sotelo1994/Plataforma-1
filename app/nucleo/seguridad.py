from functools import wraps

from flask import flash, redirect, session, url_for


# Pantalla de inicio de cada rol
INICIO_POR_ROL = {
    'admin': 'admin.inicio',
    'docente': 'docente.inicio',
    'estudiante': 'dashboard.dash_view',
    'aspirante': 'aspirante.inicio',
    'administrativo': 'personal.inicio',
    'auxiliar': 'personal.inicio',
}


def destino_por_rol(rol):
    return url_for(INICIO_POR_ROL.get(rol, 'autenticar.login'))


def requiere_rol(*roles):
    """Permite el acceso solo a los roles indicados.

    Sin sesión, manda al login. Con una sesión de otro rol, manda a su propio inicio.
    """
    def decorador(vista):
        @wraps(vista)
        def envuelta(*args, **kwargs):
            rol = session.get('rol')
            if rol is None:
                flash('Inicie sesión para continuar.', 'error')
                return redirect(url_for('autenticar.login'))
            if rol not in roles:
                flash('No tiene acceso a esa sección.', 'error')
                return redirect(destino_por_rol(rol))
            return vista(*args, **kwargs)
        return envuelta
    return decorador
