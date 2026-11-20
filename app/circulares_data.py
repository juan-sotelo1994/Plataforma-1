"""Datos de circulares y comunicados.

Fuente única para la página web (Flask) y para la app Flutter (vía /api/circulares).
Los registros de ejemplo son de prueba: reemplázalos por los datos reales
(base de datos o archivo) cuando los tengas.
"""
from datetime import date

SEDES = {
    'medellin': {
        'nombre': 'Medellín',
        'descripcion': 'Circulares y comunicados dirigidos a la sede de Medellín.',
    },
    'marinilla': {
        'nombre': 'Marinilla',
        'descripcion': 'Circulares y comunicados dirigidos a la sede de Marinilla.',
    },
}

# Campos: id, sede, titulo, fecha, publico, resumen, url (PDF opcional)
CIRCULARES = [
    {'id': 1, 'sede': 'medellin', 'titulo': 'Calendario de evaluaciones del cuarto periodo',
     'fecha': date(2026, 11, 14), 'publico': 'Familias y estudiantes',
     'resumen': 'Fechas y horarios de las evaluaciones finales del periodo.', 'url': None},
    {'id': 2, 'sede': 'medellin', 'titulo': 'Horario especial de la última semana de clases',
     'fecha': date(2026, 11, 7), 'publico': 'Docentes y administrativos',
     'resumen': 'Ajustes de jornada y entrega de notas.', 'url': None},
    {'id': 3, 'sede': 'medellin', 'titulo': 'Inicio del proceso de matrícula 2027',
     'fecha': date(2026, 10, 28), 'publico': 'Familias',
     'resumen': 'Documentos requeridos y fechas de inscripción.', 'url': None},
    {'id': 4, 'sede': 'medellin', 'titulo': 'Suspensión de clases por jornada institucional',
     'fecha': date(2026, 9, 30), 'publico': 'Comunidad educativa',
     'resumen': 'No habrá clases el día indicado en la circular.', 'url': None},
    {'id': 5, 'sede': 'marinilla', 'titulo': 'Actividades de cierre de año escolar',
     'fecha': date(2026, 11, 12), 'publico': 'Familias y estudiantes',
     'resumen': 'Programación de actos de cierre y entrega de boletines.', 'url': None},
    {'id': 6, 'sede': 'marinilla', 'titulo': 'Protocolo de transporte escolar',
     'fecha': date(2026, 10, 15), 'publico': 'Familias',
     'resumen': 'Nuevas condiciones de ingreso y salida de la ruta.', 'url': None},
]

# Cuántas circulares se muestran como "Últimas" antes de pasar a "Anteriores"
ULTIMAS_POR_SEDE = 3


def listar(sede=None):
    """Devuelve las circulares (más recientes primero), opcionalmente de una sede."""
    registros = [c for c in CIRCULARES if sede is None or c['sede'] == sede]
    return sorted(registros, key=lambda c: c['fecha'], reverse=True)


def por_sede():
    """Agrupa las circulares por sede, separando las últimas de las anteriores."""
    secciones = []
    for clave, datos in SEDES.items():
        circulares = listar(clave)
        secciones.append({
            'clave': clave,
            'nombre': datos['nombre'],
            'descripcion': datos['descripcion'],
            'ultimas': circulares[:ULTIMAS_POR_SEDE],
            'anteriores': circulares[ULTIMAS_POR_SEDE:],
        })
    return secciones
