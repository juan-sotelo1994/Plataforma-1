from flask import Blueprint, jsonify, request

from circulares_data import SEDES, listar


api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/salud')
def salud():
    return jsonify(estado='ok')


@api_bp.route('/circulares')
def circulares():
    """Circulares en JSON. Parámetro opcional: ?sede=medellin|marinilla"""
    sede = request.args.get('sede')
    if sede is not None and sede not in SEDES:
        return jsonify(error='Sede no encontrada'), 404

    datos = [{**c, 'fecha': c['fecha'].isoformat()} for c in listar(sede)]
    return jsonify(datos)
