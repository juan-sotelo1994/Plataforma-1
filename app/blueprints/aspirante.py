import io
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

from nucleo.db import get_db
from nucleo.seguridad import requiere_rol
from servicios.comprobante import generar_comprobante
from servicios.documentos import guardar_documento
from servicios.geografia import DEPARTAMENTOS


aspirante_bp = Blueprint('aspirante', __name__, url_prefix='/aspirante')

TIPOS_DOCUMENTO = ['CÉDULA DE CIUDADANÍA', 'TARJETA DE IDENTIDAD', 'CÉDULA DE EXTRANJERÍA', 'PASAPORTE']
SEXOS = ['Masculino', 'Femenino']
GRADOS_ANTERIORES = ['9°', '10°', '11°']
MAX_HERMANOS = 15

# Pestañas del formulario
PASO_ASPIRANTE, PASO_PADRES, PASO_DOCUMENTOS, PASO_ACADEMICO = 1, 2, 3, 4
TITULOS_PASOS = {
    PASO_ASPIRANTE: 'Datos del aspirante',
    PASO_PADRES: 'Datos de los padres y familia',
    PASO_DOCUMENTOS: 'Documentos',
    PASO_ACADEMICO: 'Datos académicos',
}

# Campos de cada pestaña de datos: (columna, etiqueta, obligatorio)
PASOS = {
    PASO_ASPIRANTE: [
        ('tipo_documento', 'Tipo de identificación', True),
        ('documento', 'Número de documento', True),
        ('primer_nombre', 'Primer nombre', True),
        ('segundo_nombre', 'Segundo nombre', False),
        ('primer_apellido', 'Primer apellido', True),
        ('segundo_apellido', 'Segundo apellido', False),
        ('sexo', 'Sexo', True),
        ('pais', 'País', True),
        ('departamento', 'Departamento', True),
        ('ciudad', 'Municipio', True),
        ('direccion', 'Dirección', True),
        ('telefono', 'Teléfono', False),
        ('celular', 'Celular', True),
    ],
    PASO_PADRES: [
        ('nombre_padre', 'Nombre completo del padre', True),
        ('documento_padre', 'Documento del padre', True),
        ('telefono_padre', 'Contacto del padre', True),
        ('nombre_madre', 'Nombre completo de la madre', True),
        ('documento_madre', 'Documento de la madre', True),
        ('telefono_madre', 'Contacto de la madre', True),
    ],
    PASO_ACADEMICO: [
        ('colegio_anterior', 'Nombre del colegio anterior', True),
        ('grado_anterior', 'Último grado cursado', True),
        ('anio_anterior', 'Año de finalización', True),
    ],
}

SECCION_ACADEMICA = 'academico'


def _datos_aspirante(aspirante_id, con_prefill=True):
    fila = get_db().execute(
        "SELECT a.*, j.nombre AS jornada FROM aspirantes a "
        "LEFT JOIN jornadas j ON j.id = a.jornada_id WHERE a.id = ?", (aspirante_id,)).fetchone()
    datos = dict(fila)
    # La columna puede guardarse como texto en bases migradas: se lee siempre como número
    numero = datos.get('numero_hermanos')
    datos['numero_hermanos'] = int(numero) if str(numero if numero is not None else '').strip().isdigit() else None
    datos['hermanos'] = [dict(h) for h in get_db().execute(
        'SELECT nombre, edad, parentesco FROM hermanos WHERE aspirante_id = ? ORDER BY orden, id',
        (aspirante_id,)).fetchall()]
    if not con_prefill:
        return datos
    # Inscripciones hechas antes de separar los nombres: se reparten desde nombres y apellidos
    if not datos['primer_nombre'] and datos['nombres']:
        partes = datos['nombres'].split()
        datos['primer_nombre'], datos['segundo_nombre'] = partes[0], ' '.join(partes[1:])
    if not datos['primer_apellido'] and datos['apellidos']:
        partes = datos['apellidos'].split()
        datos['primer_apellido'], datos['segundo_apellido'] = partes[0], ' '.join(partes[1:])
    return datos


def _requisitos_con_documento(aspirante_id):
    return get_db().execute(
        "SELECT r.id, r.nombre, r.descripcion, r.obligatorio, r.formatos, r.seccion, "
        "d.nombre_original, d.nombre_archivo, d.estado, d.observacion "
        "FROM requisitos r "
        "LEFT JOIN documentos_aspirante d ON d.requisito_id = r.id AND d.aspirante_id = ? "
        "WHERE r.activo = 1 ORDER BY r.id", (aspirante_id,)).fetchall()


def _de_documentos(requisitos):
    """Documentos de la pestaña Documentos (todo lo que no es académico)."""
    return [r for r in requisitos if r['seccion'] != SECCION_ACADEMICA]


def _de_academico(requisitos):
    return [r for r in requisitos if r['seccion'] == SECCION_ACADEMICA]


def _campos_faltantes(paso, aspirante):
    faltan = [etiqueta for columna, etiqueta, obligatorio in PASOS[paso]
              if obligatorio and not (aspirante[columna] or '').strip()]
    if paso == PASO_PADRES:
        numero = aspirante['numero_hermanos']
        if numero is None or str(numero).strip() == '':
            faltan.append('Número de hermanos')
        elif len(aspirante['hermanos']) < int(numero):
            faltan.append('Datos de los hermanos')
    return faltan


def _documentos_faltantes(requisitos):
    return [req['nombre'] for req in requisitos if req['obligatorio'] and req['estado'] is None]


def _pasos_completos(aspirante_id):
    """Indica qué pestañas están completas, según lo guardado en la base."""
    aspirante = _datos_aspirante(aspirante_id, con_prefill=False)
    requisitos = _requisitos_con_documento(aspirante_id)
    return {
        PASO_ASPIRANTE: not _campos_faltantes(PASO_ASPIRANTE, aspirante),
        PASO_PADRES: not _campos_faltantes(PASO_PADRES, aspirante),
        PASO_DOCUMENTOS: not _documentos_faltantes(_de_documentos(requisitos)),
        PASO_ACADEMICO: not (_campos_faltantes(PASO_ACADEMICO, aspirante)
                             or _documentos_faltantes(_de_academico(requisitos))),
    }


@aspirante_bp.route('/')
@requiere_rol('aspirante')
def inicio():
    aspirante_id = session['persona_id']
    aspirante = _datos_aspirante(aspirante_id)
    requisitos = _requisitos_con_documento(aspirante_id)
    completos = _pasos_completos(aspirante_id)

    paso = request.args.get('paso', default=PASO_ASPIRANTE, type=int)
    if paso not in TITULOS_PASOS:
        paso = PASO_ASPIRANTE
    # Cada pestaña se abre solo cuando las anteriores de datos están completas
    if paso == PASO_PADRES and not completos[PASO_ASPIRANTE]:
        flash('Complete primero los datos del aspirante para continuar.', 'error')
        paso = PASO_ASPIRANTE
    if paso in (PASO_DOCUMENTOS, PASO_ACADEMICO) and not (completos[PASO_ASPIRANTE] and completos[PASO_PADRES]):
        flash('Complete primero los datos del aspirante y de los padres para continuar.', 'error')
        paso = PASO_ASPIRANTE if not completos[PASO_ASPIRANTE] else PASO_PADRES

    if paso == PASO_DOCUMENTOS:
        requisitos_paso = _de_documentos(requisitos)
        faltan = _documentos_faltantes(requisitos_paso)
    elif paso == PASO_ACADEMICO:
        requisitos_paso = _de_academico(requisitos)
        faltan = _campos_faltantes(PASO_ACADEMICO, aspirante) + _documentos_faltantes(requisitos_paso)
    else:
        requisitos_paso = []
        faltan = _campos_faltantes(paso, aspirante)

    return render_template(
        'aspirante/inicio.html', aspirante=aspirante, paso=paso, titulo_paso=TITULOS_PASOS[paso],
        campos=PASOS.get(paso, []), requisitos=requisitos_paso, tipos_documento=TIPOS_DOCUMENTO,
        sexos=SEXOS, departamentos=DEPARTAMENTOS, grados_anteriores=GRADOS_ANTERIORES,
        completos=completos, faltan=faltan, PASO_DOCUMENTOS=PASO_DOCUMENTOS, PASO_ACADEMICO=PASO_ACADEMICO,
        todo_completo=all(completos.values()), descargar=request.args.get('completo') == '1')


@aspirante_bp.route('/comprobante')
@requiere_rol('aspirante')
def comprobante():
    aspirante_id = session['persona_id']
    if not all(_pasos_completos(aspirante_id).values()):
        flash('Complete todos los pasos para descargar el comprobante.', 'error')
        return redirect(url_for('aspirante.inicio'))
    datos = _datos_aspirante(aspirante_id, con_prefill=False)
    documentos = [dict(fila) for fila in _requisitos_con_documento(aspirante_id)]
    pdf = generar_comprobante(datos, datos['hermanos'], documentos)
    return send_file(io.BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
                     download_name='comprobante_inscripcion.pdf')


@aspirante_bp.route('/paso/<int:paso>', methods=['POST'])
@requiere_rol('aspirante')
def guardar_paso(paso):
    if paso not in TITULOS_PASOS:
        return redirect(url_for('aspirante.inicio'))
    if paso == PASO_DOCUMENTOS:
        return _guardar_documentos()
    if paso == PASO_ACADEMICO:
        return _guardar_academico()
    return _guardar_datos(paso)


def _validar_aspirante(valores):
    """Validaciones propias de la pestaña del aspirante. Devuelve un mensaje o None."""
    if valores['tipo_documento'] not in TIPOS_DOCUMENTO or valores['sexo'] not in SEXOS:
        return 'Seleccione el tipo de identificación y el sexo de la lista.'
    if valores['departamento'] not in DEPARTAMENTOS:
        return 'Seleccione el departamento de la lista.'
    return None


def _validar_academico(valores):
    if valores['grado_anterior'] not in GRADOS_ANTERIORES:
        return 'Seleccione el último grado cursado de la lista.'
    if not (valores['anio_anterior'].isdigit() and 1990 <= int(valores['anio_anterior']) <= 2100):
        return 'Escriba un año de finalización válido (por ejemplo, 2025).'
    return None


def _guardar_datos(paso):
    aspirante_id = session['persona_id']
    db = get_db()
    valores = {columna: request.form.get(columna, '').strip()[:120] for columna, _, _ in PASOS[paso]}

    if paso == PASO_ASPIRANTE:
        mensaje = _validar_aspirante(valores)
        if mensaje:
            flash(mensaje, 'error')
            return redirect(url_for('aspirante.inicio', paso=paso))
        valores['nombres'] = ' '.join(p for p in (valores['primer_nombre'], valores['segundo_nombre']) if p)
        valores['apellidos'] = ' '.join(p for p in (valores['primer_apellido'], valores['segundo_apellido']) if p)

    vacios = [etiqueta for columna, etiqueta, obligatorio in PASOS[paso] if obligatorio and not valores[columna]]
    if vacios:
        flash('Complete: ' + ', '.join(vacios) + '.', 'error')
        return redirect(url_for('aspirante.inicio', paso=paso))

    hermanos = []
    if paso == PASO_PADRES:
        numero_bruto = request.form.get('numero_hermanos', '').strip()
        if not numero_bruto.isdigit() or int(numero_bruto) > MAX_HERMANOS:
            flash(f'Indique el número de hermanos (de 0 a {MAX_HERMANOS}).', 'error')
            return redirect(url_for('aspirante.inicio', paso=PASO_PADRES))
        numero = int(numero_bruto)
        for i in range(numero):
            nombre = request.form.get(f'hermano_nombre_{i}', '').strip()[:120]
            edad = request.form.get(f'hermano_edad_{i}', '').strip()
            parentesco = request.form.get(f'hermano_parentesco_{i}', '').strip()[:60]
            if not nombre or not parentesco or not edad.isdigit() or int(edad) > 120:
                flash(f'Complete nombre, edad (de 0 a 120) y parentesco del hermano {i + 1}.', 'error')
                return redirect(url_for('aspirante.inicio', paso=PASO_PADRES))
            hermanos.append((nombre, int(edad), parentesco, i))
        valores['numero_hermanos'] = numero

    try:
        db.execute('UPDATE aspirantes SET ' + ', '.join(f'{c} = ?' for c in valores) + ' WHERE id = ?',
                   [valores[c] for c in valores] + [aspirante_id])
        if paso == PASO_PADRES:
            db.execute('DELETE FROM hermanos WHERE aspirante_id = ?', (aspirante_id,))
            db.executemany(
                'INSERT INTO hermanos (aspirante_id, nombre, edad, parentesco, orden) VALUES (?, ?, ?, ?, ?)',
                [(aspirante_id, nombre, edad, parentesco, orden) for nombre, edad, parentesco, orden in hermanos])
        db.commit()
    except sqlite3.IntegrityError:
        flash('Ese número de documento ya está registrado en otra inscripción. Los datos no se guardaron.', 'error')
        return redirect(url_for('aspirante.inicio', paso=paso))

    flash('Datos guardados.', 'ok')
    if paso == PASO_ASPIRANTE:
        return redirect(url_for('aspirante.inicio', paso=PASO_PADRES))
    return redirect(url_for('aspirante.inicio', paso=PASO_DOCUMENTOS if _pasos_completos(aspirante_id)[PASO_PADRES] else PASO_PADRES))


def _procesar_archivos(requisitos):
    """Guarda los archivos que el aspirante haya elegido. Devuelve (subidos, errores)."""
    aspirante_id = session['persona_id']
    subidos, errores = [], []
    for requisito in requisitos:
        archivo = request.files.get(f'archivo_{requisito["id"]}')
        if archivo is None or not archivo.filename:
            continue
        if requisito['estado'] == 'aprobado':
            errores.append(f'{requisito["nombre"]}: ya fue aprobado, no se reemplaza.')
            continue
        ok, mensaje = guardar_documento(aspirante_id, requisito['id'], archivo)
        (subidos if ok else errores).append(
            f'{requisito["nombre"]}: subido.' if ok else f'{requisito["nombre"]}: {mensaje}')
    return subidos, errores


def _guardar_documentos():
    aspirante_id = session['persona_id']
    completos = _pasos_completos(aspirante_id)
    if not (completos[PASO_ASPIRANTE] and completos[PASO_PADRES]):
        flash('Complete primero los datos del aspirante y de los padres.', 'error')
        return redirect(url_for('aspirante.inicio', paso=PASO_ASPIRANTE))

    subidos, errores = _procesar_archivos(_de_documentos(_requisitos_con_documento(aspirante_id)))
    for linea in subidos:
        flash(linea, 'ok')
    for linea in errores:
        flash(linea, 'error')

    faltan = _documentos_faltantes(_de_documentos(_requisitos_con_documento(aspirante_id)))
    if faltan:
        flash('Falta por subir: ' + ', '.join(faltan) + '.', 'error' if errores else 'ok')
        return redirect(url_for('aspirante.inicio', paso=PASO_DOCUMENTOS))
    flash('Documentos completos. Continúe con los datos académicos.', 'ok')
    return redirect(url_for('aspirante.inicio', paso=PASO_ACADEMICO))


def _guardar_academico():
    aspirante_id = session['persona_id']
    completos = _pasos_completos(aspirante_id)
    if not (completos[PASO_ASPIRANTE] and completos[PASO_PADRES]):
        flash('Complete primero los datos del aspirante y de los padres.', 'error')
        return redirect(url_for('aspirante.inicio', paso=PASO_ASPIRANTE))

    valores = {columna: request.form.get(columna, '').strip()[:120] for columna, _, _ in PASOS[PASO_ACADEMICO]}
    vacios = [etiqueta for columna, etiqueta, obligatorio in PASOS[PASO_ACADEMICO] if obligatorio and not valores[columna]]
    if vacios:
        flash('Complete: ' + ', '.join(vacios) + '.', 'error')
        return redirect(url_for('aspirante.inicio', paso=PASO_ACADEMICO))
    mensaje = _validar_academico(valores)
    if mensaje:
        flash(mensaje, 'error')
        return redirect(url_for('aspirante.inicio', paso=PASO_ACADEMICO))

    db = get_db()
    db.execute('UPDATE aspirantes SET ' + ', '.join(f'{c} = ?' for c in valores) + ' WHERE id = ?',
               [valores[c] for c in valores] + [aspirante_id])
    db.commit()

    subidos, errores = _procesar_archivos(_de_academico(_requisitos_con_documento(aspirante_id)))
    for linea in subidos:
        flash(linea, 'ok')
    for linea in errores:
        flash(linea, 'error')

    aspirante = _datos_aspirante(aspirante_id, con_prefill=False)
    requisitos = _de_academico(_requisitos_con_documento(aspirante_id))
    faltan = _campos_faltantes(PASO_ACADEMICO, aspirante) + _documentos_faltantes(requisitos)
    if faltan:
        flash('Falta: ' + ', '.join(faltan) + '.', 'error' if errores else 'ok')
        return redirect(url_for('aspirante.inicio', paso=PASO_ACADEMICO))
    return redirect(url_for('aspirante.inicio', paso=PASO_ACADEMICO, completo=1))
