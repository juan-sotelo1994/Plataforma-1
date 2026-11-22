# Resumen para continuar en Linux

Este archivo resume lo que se construyó en la sesión de desarrollo para que se pueda seguir en otro equipo.

## 1. Estado de Git

| Rama | Commit | Contenido | Subida a GitHub |
|---|---|---|---|
| `version7` | `02b0ced` | Base anterior (notas, aspirantes, docentes) | Sí |
| `version8` | `9800e98` | Multi-sede, superadministrador, inscripción en dos pasos, CSV de estudiantes, plazos de notas | No |
| `version9` | `b4112fe` | Monitoreo general, auditoría por sede, matrícula financiera (recibos) | No |
| `version10` | (este commit) | Todo lo demás de esta sesión (ver sección 3) | No |

El PR de `version9` no se creó: `gh` no está autenticado en el equipo de Windows.

## 2. Cómo pasar al equipo Linux

1. En Windows, subir las ramas: `git push -u origin version8`, luego `version9` y `version10`.
2. En Linux: `git clone https://github.com/juan-sotelo1994/Plataforma-1.git` y `git checkout version10`.
3. Copiar **a mano** (están en `.gitignore` y no viajan por Git):
   - `app/.env`: contiene `SECRET_KEY`, `DEV_CORREO` y `DEV_CONTRASENA` del superadministrador. No lo subir a GitHub.
   - `app/instance/`: bases de datos (`central.db` y las bases de cada sede). Sin esto, las sedes y los datos de prueba no existen.
   - `app/uploads/`: documentos, recibos de matrícula, hojas de vida y fotos de estudiantes.
   - Si no se copian, la plataforma crea bases vacías al arrancar y el superadministrador vuelve a entrar con la clave del `.env`.

## 3. Puesta en marcha en Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
cd app
python app.py
```

- Corre en `http://127.0.0.1:5712`.
- `requirements.txt` solo lista `flask`, `python-dotenv` y `reportlab`. `Pillow` (usado por `servicios/comprobante.py`) lo instala `reportlab`; si falla, instalar `pillow` a mano.
- No hay rutas fijas de Windows en el código.
- Si cambias archivos de `app/.env` o de `nucleo/sedes.py`, reinicia el servidor: la tabla `credencial_superadmin` se crea al arrancar.

## 4. Qué se construyó (por perfil)

**Superadministrador** (cuenta del `.env`, o la contraseña nueva guardada en la base central)
- Crea sedes y administradores de sede; cada sede tiene su propia base SQLite.
- Vista de solo lectura de cada sede: resumen, estudiantes, docentes, cursos, aspirantes.
- **Monitoreo general**: cifras por sede (estudiantes, docentes, cursos, matrículas, avance de notas, aspirantes, última actividad).
- Dentro de cada sede: **Horarios**, **Avances** (materias con porcentaje de notas, plazo y estado) y **Auditoría** (buscador, últimos 500 movimientos).
- Cambio de contraseña desde **CONFIGURACIÓN**. Después de cambiarla, la nueva reemplaza a la del `.env`.

**Administrador de sede**
- Estudiantes: crear, editar, exportar e importar CSV (validación completa antes de guardar), habilitar y deshabilitar acceso, restablecer contraseñas.
- Cursos (grupos por ciclo) y materias; matrículas; plazos para subir notas.
- Aspirantes: revisión de documentos, habilitación como estudiantes.
- **Matrícula financiera** (menú propio): lista de estudiantes con su recibo, estado (Sin recibo, Por revisar, Pagada, Rechazada) y fecha de pago. Filtros por nombre, documento, curso y jornada. Aprobar o rechazar con motivo.
- Notas: criterios de evaluación, notas por criterio, definitiva, exportación CSV/PDF, observación del docente por estudiante.

**Docente**
- Notas por criterio con plazo (no puede cambiarlas cuando el plazo cierra).
- Observación por estudiante (se guarda con "Guardar notas").
- Hoja de vida y documentos de formación.

**Estudiante** (portal `/panel`)
- **Actualizar mis datos** y **Mi foto** (JPG o PNG, máximo 2 MB).
- **Notas**: primero se elige el periodo. Muestra un resumen con código, materia, ciclo, nota definitiva, veces cursada y **promedio parcial** (promedio simple de las definitivas). Debajo, cada asignatura con su tabla de criterios y el botón **Ver más** (desglose: nota, porcentaje y aporte de cada criterio, y acumulado).
- **Notas (PDF)**: reporte de calificaciones con foto, materias por periodo, estrategias con su porcentaje y aporte, observación del docente y promedio parcial por periodo.
- **Matrícula financiera**: sube recibo (PDF, JPG o PNG) por modalidad (mensualidad, trimestral, semestral) y periodo. Ve el estado y el motivo si lo rechazan.

**Aspirante**
- Inscripción en dos pasos: datos y sede primero; la contraseña se crea en la pantalla siguiente.
- Documentos y formulario de inscripción; el certificado de discapacidad se exige solo si responde "Sí".

## 5. Reglas de trabajo acordadas

- Los commits se hacen solo cuando se pide. Mensaje con la línea `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`.
- No copiar logos, nombres ni fotos de otras instituciones. Usar los datos de la plataforma (`EMPRESA` en `blueprints/web.py`).
- Las tablas nuevas que solo existen en algunas bases se crean al usarlas (`auditoria`, `recibos_matricula`, `observaciones_notas`, `fotos_estudiantes`), así las bases existentes no se rompen.
- Una base por sede (`instance/sede_*.db`); la central (`instance/central.db`) guarda sedes, administradores de sede y la contraseña del superadministrador.

## 6. Pendientes

- **Migrar a PostgreSQL** cuando la base lógica esté terminada. Hay SQL específico de SQLite: `PRAGMA`, `INSERT OR IGNORE`, `AUTOINCREMENT`, `datetime('now')`, reconstrucción de tablas en `nucleo/db.py`, y una base por sede.
- Subir `version8`, `version9` y `version10`, y crear el PR (requiere `gh auth login`).
- Revisión visual en el navegador de: inscripción, monitoreo, matrícula financiera, notas del estudiante, configuración y reporte PDF. Solo se probó con pruebas automáticas sobre copias de la base.
- Foto del estudiante: hoy solo la sube el estudiante; el administrador no puede subirla.
- Reporte PDF: falta la columna de ciclo (sí aparece en la página de notas) y la columna "Tipo" (CO/CE), que el sistema no guarda.
- Matrícula financiera: el monitoreo general no cuenta los recibos pendientes.
- Aspirantes: la lista no tiene filtros de curso y jornada porque sus datos no los incluyen.
- Enlaces de **Biblioteca virtual** y **Moodle**: siguen en `#` (`BIBLIOTECA_URL` y `MOODLE_URL` en `blueprints/dash.py`).
- Auditoría: no registra la edición de hojas de vida de docentes ni las consultas.
- Promedio parcial: es promedio simple; si se quiere ponderado por créditos, cambiar `_promedio` y el cálculo de la página de notas.
- Cambiar la contraseña inicial del superadministrador (está en `app/.env`).

## 7. Mapa de archivos clave

- `app.py`: arranque y registro de blueprints.
- `nucleo/db.py`: esquema de cada sede y migraciones; `nucleo/sedes.py`: base central, sedes y `credencial_superadmin`.
- `nucleo/auditoria.py`: registro de acciones por sede.
- `nucleo/seguridad.py`: roles y `requiere_rol`.
- `blueprints/auth.py`: ingreso, cuentas y **CONFIGURACIÓN**.
- `blueprints/superadmin.py`: sedes, administradores, monitoreo, horarios, avances y auditoría.
- `blueprints/admin.py`: módulo del administrador de sede.
- `blueprints/docente.py`: portal del docente.
- `blueprints/dash.py`: portal del estudiante (datos, foto, notas, notas PDF, matrícula).
- `blueprints/aspirante.py`, `blueprints/web.py`: inscripción pública y portal del aspirante.
- `servicios/notas.py`: criterios, definitivas, plazos y observaciones.
- `servicios/reporte_notas.py`: PDF de notas del estudiante.
- `servicios/matricula_financiera.py`: recibos de matrícula.
- `servicios/fotos.py`: foto del estudiante.
- `servicios/estudiantes_csv.py`: exportar e importar estudiantes.
- `templates/_filtros.html`: barra de filtros común.
- `templates/_notas_curso.html`: tabla de notas compartida por docente y administrador.
- `templates/auth/configuracion.html` y `base_configuracion.html`: cambio de contraseña.
