"""Exportar e importar estudiantes en CSV, para migrar datos desde otra plataforma.

Solo datos escritos: los documentos en PDF no pasan por aquí.
El separador es ";" (como lo espera Excel en español); al importar se aceptan ";" o ",".
"""
import csv
import datetime
import io
import sqlite3

from blueprints.aspirante import ESTADOS_CIVILES, SI_NO, TIPOS_SANGRE

# Columnas del archivo, en el orden en que se exportan. Jornada va por nombre.
COLUMNAS = [
    'codigo', 'nombres', 'apellidos', 'documento', 'correo', 'programa', 'jornada',
    'telefono', 'celular', 'direccion', 'pais', 'departamento', 'ciudad',
    'fecha_nacimiento', 'estado_civil', 'tipo_sangre', 'lugar_expedicion', 'fecha_expedicion',
    'tiene_discapacidad', 'discapacidad',
    'nombre_padre', 'documento_padre', 'telefono_padre',
    'nombre_madre', 'documento_madre', 'telefono_madre',
]
OBLIGATORIAS = ('codigo', 'nombres', 'apellidos', 'documento')
FECHAS = ('fecha_nacimiento', 'fecha_expedicion')
TEXTOS_OPCIONALES = (
    'correo', 'programa', 'telefono', 'celular', 'direccion', 'pais', 'departamento', 'ciudad',
    'estado_civil', 'tipo_sangre', 'lugar_expedicion', 'tiene_discapacidad', 'discapacidad',
    'nombre_padre', 'documento_padre', 'telefono_padre', 'nombre_madre', 'documento_madre', 'telefono_madre',
)
MAX_ERRORES_MOSTRADOS = 8
BOM = '﻿'


def exportar(db):
    filas = db.execute(
        'SELECT e.*, j.nombre AS jornada FROM estudiantes e '
        'LEFT JOIN jornadas j ON j.id = e.jornada_id ORDER BY e.apellidos, e.nombres').fetchall()
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=';')
    escritor.writerow(COLUMNAS)
    for fila in filas:
        escritor.writerow(['' if fila[c] is None else fila[c] for c in COLUMNAS])
    return (BOM + salida.getvalue()).encode('utf-8')


def formato():
    """Archivo solo con los encabezados: sirve de plantilla para llenar."""
    salida = io.StringIO()
    csv.writer(salida, delimiter=';').writerow(COLUMNAS)
    return (BOM + salida.getvalue()).encode('utf-8')


def _texto(contenido):
    try:
        return contenido.decode('utf-8-sig')
    except UnicodeDecodeError:
        return contenido.decode('cp1252', errors='replace')


def _validar_fila(fila, jornadas):
    """Devuelve (datos, error). Los datos son los valores listos para guardar."""
    datos = {c: (fila.get(c) or '').strip() for c in COLUMNAS}
    for c in OBLIGATORIAS:
        if not datos[c]:
            return None, f'falta {c}'

    nombre_jornada = datos.pop('jornada')
    if nombre_jornada:
        if nombre_jornada.lower() not in jornadas:
            return None, f'la jornada "{nombre_jornada}" no existe (use el nombre tal como aparece en Jornadas)'
        datos['jornada_id'] = jornadas[nombre_jornada.lower()]
    else:
        datos['jornada_id'] = None

    for c in FECHAS:
        if datos[c]:
            try:
                datetime.date.fromisoformat(datos[c])
            except ValueError:
                return None, f'{c} debe tener el formato AAAA-MM-DD'
    if datos['estado_civil'] and datos['estado_civil'] not in ESTADOS_CIVILES:
        return None, 'estado_civil no está en la lista permitida'
    if datos['tipo_sangre'] and datos['tipo_sangre'] not in TIPOS_SANGRE:
        return None, 'tipo_sangre no está en la lista permitida (por ejemplo O+ o AB-)'
    if datos['tiene_discapacidad'] == 'Si':
        datos['tiene_discapacidad'] = 'Sí'
    if datos['tiene_discapacidad'] and datos['tiene_discapacidad'] not in SI_NO:
        return None, 'tiene_discapacidad debe ser Sí o No'
    if datos['tiene_discapacidad'] != 'Sí':
        datos['discapacidad'] = ''

    for c in TEXTOS_OPCIONALES + FECHAS:
        datos[c] = datos[c] or None
    if datos['correo']:
        datos['correo'] = datos['correo'].lower()
    return datos, None


def importar(db, contenido):
    """Crea o actualiza estudiantes (por documento). Si alguna fila tiene errores, no se guarda ninguna.

    Devuelve (ok, mensajes, creados, actualizados).
    """
    texto = _texto(contenido)
    primera = texto.split('\n', 1)[0]
    separador = ';' if primera.count(';') >= primera.count(',') else ','
    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)
    if not lector.fieldnames:
        return False, ['El archivo está vacío.'], 0, 0
    lector.fieldnames = [(n or '').strip().lower() for n in lector.fieldnames]
    faltantes = [c for c in OBLIGATORIAS if c not in lector.fieldnames]
    if faltantes:
        return False, ['Al archivo le faltan las columnas: ' + ', '.join(faltantes) + '.'], 0, 0

    jornadas = {f['nombre'].lower(): f['id'] for f in db.execute('SELECT id, nombre FROM jornadas')}
    errores, validos, vistos = [], [], set()
    for numero, fila in enumerate(lector, start=2):
        if not any((v or '').strip() for v in fila.values()):
            continue
        datos, error = _validar_fila(fila, jornadas)
        if error is None and datos['documento'] in vistos:
            error = 'el documento aparece más de una vez en el archivo'
        if error:
            errores.append(f'Fila {numero}: {error}.')
        else:
            vistos.add(datos['documento'])
            validos.append(datos)
    if errores:
        extra = len(errores) - MAX_ERRORES_MOSTRADOS
        mensajes = errores[:MAX_ERRORES_MOSTRADOS]
        if extra > 0:
            mensajes.append(f'Y {extra} error(es) más.')
        return False, ['No se guardó nada. Corrija el archivo y vuelva a subirlo.'] + mensajes, 0, 0

    creados = actualizados = 0
    try:
        for datos in validos:
            existente = db.execute('SELECT id FROM estudiantes WHERE documento = ?', (datos['documento'],)).fetchone()
            if existente:
                db.execute('UPDATE estudiantes SET ' + ', '.join(f'{c} = ?' for c in datos) + ' WHERE id = ?',
                           [*datos.values(), existente['id']])
                actualizados += 1
            else:
                db.execute('INSERT INTO estudiantes (' + ', '.join(datos) + ') VALUES (' +
                           ', '.join('?' for _ in datos) + ')', list(datos.values()))
                creados += 1
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return False, ['No se guardó nada: un código de estudiante ya existe con otro documento.'], 0, 0
    return True, [], creados, actualizados
