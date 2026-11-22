

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from nucleo.db import IntegrityError, get_db
from nucleo.seguridad import requiere_rol
from servicios.geografia import DEPARTAMENTOS
from servicios.hojas import guardar_hoja
from servicios.documentos_docente import ANTECEDENTES, TIPOS, guardar as guardar_documento_docente, listar as listar_documentos


datos_docente_bp = Blueprint('datos_docente', __name__, url_prefix='/docente')

SEXOS = ['Masculino', 'Femenino']

# Campos de cada paso: (columna, etiqueta, obligatorio)
PASOS_DOCENTE = {
    1: [
        ('nombres', 'Nombres', True),
        ('apellidos', 'Apellidos', True),
        ('documento', 'Número de documento', True),
        ('sexo', 'Sexo', True),
        ('telefono', 'Teléfono', False),
        ('celular', 'Celular', True),
        ('pais', 'País', True),
        ('departamento', 'Departamento', True),
        ('ciudad', 'Municipio', True),
        ('direccion', 'Dirección', True),
    ],
    2: [
        ('especialidad', 'Especialidad o formación', True),
    ],
}
TITULOS = {1: 'Datos personales', 2: 'Formación y hoja de vida', 3: 'Antecedentes'}
PASO_ANTECEDENTES = 3


def _docente(docente_id):
    return dict(get_db().execute('SELECT * FROM docentes WHERE id = ?', (docente_id,)).fetchone())


def _hoja(docente_id):
    return get_db().execute('SELECT nombre_original, subido_en FROM hojas_de_vida WHERE docente_id = ?',
                            (docente_id,)).fetchone()


def _faltantes(paso, docente, hoja, documentos):
    faltan = [etiqueta for columna, etiqueta, obligatorio in PASOS_DOCENTE[paso]
              if obligatorio and not (docente.get(columna) or '').strip()]
    if paso == 2:
        if hoja is None:
            faltan.append('Hoja de vida (PDF o DOC)')
        faltan += [etiqueta for tipo, (etiqueta, obligatorio) in TIPOS.items()
                   if obligatorio and tipo not in documentos]
    return faltan


def _faltantes_antecedentes(documentos):
    return [etiqueta for tipo, (etiqueta, _, obligatorio) in ANTECEDENTES.items()
            if obligatorio and tipo not in documentos]


@datos_docente_bp.route('/datos')
@requiere_rol('docente')
def datos():
    docente_id = session['persona_id']
    docente = _docente(docente_id)
    hoja = _hoja(docente_id)
    documentos = listar_documentos(docente_id)
    completo_1 = not _faltantes(1, docente, hoja, documentos)
    completo_2 = not _faltantes(2, docente, hoja, documentos)

    paso = request.args.get('paso', default=1, type=int)
    if paso not in (1, 2, PASO_ANTECEDENTES):
        paso = 1
    if paso == 2 and not completo_1:
        flash('Complete primero sus datos personales para continuar.', 'error')
        paso = 1
    if paso == PASO_ANTECEDENTES and not (completo_1 and completo_2):
        flash('Complete primero sus datos y su formación para continuar.', 'error')
        paso = 1 if not completo_1 else 2

    completos = {1: completo_1, 2: completo_2, PASO_ANTECEDENTES: not _faltantes_antecedentes(documentos)}
    if paso == PASO_ANTECEDENTES:
        faltan = _faltantes_antecedentes(documentos)
    else:
        faltan = _faltantes(paso, docente, hoja, documentos)
    return render_template('docente/datos.html', docente=docente, hoja=hoja, paso=paso, titulo=TITULOS[paso],
                           campos=PASOS_DOCENTE.get(paso, []), sexos=SEXOS, departamentos=DEPARTAMENTOS,
                           completos=completos, faltan=faltan, tipos=TIPOS, documentos=documentos,
                           antecedentes=ANTECEDENTES, PASO_ANTECEDENTES=PASO_ANTECEDENTES)


@datos_docente_bp.route('/datos/paso/<int:paso>', methods=['POST'])
@requiere_rol('docente')
def guardar(paso):
    docente_id = session['persona_id']
    if paso == PASO_ANTECEDENTES:
        documentos = listar_documentos(docente_id)
        if not (not _faltantes(1, _docente(docente_id), _hoja(docente_id), documentos)
                and not _faltantes(2, _docente(docente_id), _hoja(docente_id), documentos)):
            flash('Complete primero sus datos y su formación.', 'error')
            return redirect(url_for('datos_docente.datos', paso=1))
        subidos = 0
        for tipo in ANTECEDENTES:
            archivo = request.files.get(f'doc_{tipo}')
            if archivo is not None and archivo.filename:
                ok, mensaje = guardar_documento_docente(docente_id, tipo, archivo)
                if ok:
                    subidos += 1
                    flash(f'{ANTECEDENTES[tipo][0]}: archivo guardado.', 'ok')
                else:
                    flash(f'{ANTECEDENTES[tipo][0]}: {mensaje}', 'error')
        faltan = _faltantes_antecedentes(listar_documentos(docente_id))
        if faltan:
            flash('Falta por subir: ' + ', '.join(faltan) + '.', 'error' if subidos == 0 else 'ok')
            return redirect(url_for('datos_docente.datos', paso=PASO_ANTECEDENTES))
        flash('Antecedentes completos. Sus datos y documentos están listos.', 'ok')
        return redirect(url_for('datos_docente.datos', paso=PASO_ANTECEDENTES))

    if paso not in PASOS_DOCENTE:
        return redirect(url_for('datos_docente.datos'))
    db = get_db()
    valores = {columna: request.form.get(columna, '').strip()[:120] for columna, _, _ in PASOS_DOCENTE[paso]}

    if paso == 1:
        if valores['sexo'] not in SEXOS:
            flash('Seleccione el sexo de la lista.', 'error')
            return redirect(url_for('datos_docente.datos', paso=1))
        if valores['departamento'] not in DEPARTAMENTOS:
            flash('Seleccione el departamento de la lista.', 'error')
            return redirect(url_for('datos_docente.datos', paso=1))

    vacios = [etiqueta for columna, etiqueta, obligatorio in PASOS_DOCENTE[paso] if obligatorio and not valores[columna]]
    if vacios:
        flash('Complete: ' + ', '.join(vacios) + '.', 'error')
        return redirect(url_for('datos_docente.datos', paso=paso))

    try:
        db.execute('UPDATE docentes SET ' + ', '.join(f'{c} = ?' for c in valores) + ' WHERE id = ?',
                   [valores[c] for c in valores] + [docente_id])
        db.commit()
    except IntegrityError:
        flash('Ese número de documento ya está registrado para otro docente. Los datos no se guardaron.', 'error')
        return redirect(url_for('datos_docente.datos', paso=paso))

    if paso == 2:
        archivo = request.files.get('hoja_de_vida')
        if archivo is not None and archivo.filename:
            ok, mensaje = guardar_hoja(docente_id, archivo)
            if not ok:
                flash(f'Los datos se guardaron, pero la hoja de vida no: {mensaje}', 'error')
        for tipo in TIPOS:
            archivo = request.files.get(f'doc_{tipo}')
            if archivo is not None and archivo.filename:
                ok, mensaje = guardar_documento_docente(docente_id, tipo, archivo)
                if not ok:
                    flash(f'{TIPOS[tipo][0]}: {mensaje}', 'error')

    docente = _docente(docente_id)
    hoja = _hoja(docente_id)
    faltan = _faltantes(paso, docente, hoja, listar_documentos(docente_id))
    if faltan:
        flash('Datos guardados. Falta: ' + ', '.join(faltan) + '.', 'error')
        return redirect(url_for('datos_docente.datos', paso=paso))
    if paso == 1:
        flash('Datos personales guardados. Continúe con su formación.', 'ok')
        return redirect(url_for('datos_docente.datos', paso=2))
    flash('Formación y hoja de vida guardadas. Continúe con los antecedentes.', 'ok')
    return redirect(url_for('datos_docente.datos', paso=PASO_ANTECEDENTES))
