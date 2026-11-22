# Resumen para continuar en Linux

Este archivo resume lo que se construyó en la sesión de desarrollo para que se pueda seguir en otro equipo.

## 1. Estado de Git

| Rama | Commit | Contenido | Subida a GitHub |
|---|---|---|---|
| `version7` | `02b0ced` | Base anterior (notas, aspirantes, docentes) | Sí |
| `version8` | `9800e98` | Multi-sede, superadministrador, inscripción en dos pasos, CSV de estudiantes, plazos de notas | No |
| `version9` | `b4112fe` | Monitoreo general, auditoría por sede, matrícula financiera (recibos) | No |
| `version10` | `0ef780c` | Notas por periodo con ciclo, promedio parcial, PDF de notas con foto y observaciones, foto del estudiante, filtros, cambio de contraseña | Sí |
| `version11` | (este commit) | Migración de SQLite a PostgreSQL (sección 3) | No |

El PR de `version10` no se ha creado: `gh` no está autenticado en el equipo de Windows (`gh auth login`).

## 2. Cómo pasar al equipo Linux

1. **Código:** `git clone https://github.com/juan-sotelo1994/Plataforma-1.git` y `git checkout version11`.
2. **PostgreSQL** en Linux (por ejemplo `sudo apt install postgresql`). Crear el usuario `instituto_app` y la base `instituto` con dueño `instituto_app`.
3. **Datos:** copiar a mano el respaldo `app/instance/instituto.dump` (no está en GitHub porque contiene datos personales y contraseñas cifradas) y restaurarlo:
   ```bash
   pg_restore --no-owner --role=instituto_app -d instituto instituto.dump
   ```
4. **Archivos que no viajan por Git** (copiar a mano):
   - `app/.env`: `SECRET_KEY`, `DEV_CORREO`, `DEV_CONTRASENA` y `DATABASE_URL`. No subirlo a GitHub.
   - `app/uploads/`: documentos, recibos de matrícula, hojas de vida y fotos de estudiantes.
   - Las bases SQLite (`app/instance/*.db`) ya no se usan: son solo respaldo.

## 3. Base de datos PostgreSQL (version11)

- Base `instituto`. Cada sede es un **esquema** (`sede_1` = Ipiales, `sede_2` = Pupiales, y las nuevas con nombre `sede_<10 caracteres>`). El esquema `central` guarda sedes, administradores de sede y la credencial del superadministrador.
- `DATABASE_URL` en `app/.env`, con el formato `postgresql://instituto_app:CLAVE@localhost:5432/instituto`.
- `nucleo/db.py` y `nucleo/sedes.py`: conexión a PostgreSQL. `Conexion` mantiene la sintaxis de `sqlite3` (`?` como parámetro, filas por nombre o posición) y cada sentencia va dentro de un punto de guardado, así un error de duplicado no rompe la transacción.
- `nucleo/esquema_sede.sql` y `nucleo/esquema_central.sql`: tablas generadas desde el modelo SQLite. `crear_base(esquema)` crea una sede nueva y copia requisitos y configuración de `sede_1`.
- `migrar_a_postgres.py`: pasó los datos de SQLite a PostgreSQL. Ya se ejecutó; no volver a correrlo sobre `instituto` (borra y recrea los esquemas de origen).
- Cambios de SQL: `?` → `%s` (automático), `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` (automático), `lastrowid` → `RETURNING id` (automático), `datetime('now')` → `to_char(localtimestamp, …)`, `GROUP_CONCAT` → `string_agg`, `LIKE` → `ILIKE`.
- Las contraseñas de usuarios se copiaron tal cual están (ya eran hashes). La del superadministrador sigue en texto claro en `app/.env` hasta que se decida guardarla como hash.

## 4. Puesta en marcha

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
cd app
python app.py
```

- Corre en `http://127.0.0.1:5712`.
- `requirements.txt` incluye `flask`, `python-dotenv`, `reportlab` y `psycopg[binary]`.
- Si cambias `app/.env` o `nucleo/sedes.py`, reinicia el servidor.

## 5. Qué se construyó (por perfil)

**Superadministrador** (cuenta del `.env`, o la contraseña nueva guardada en la base central)
- Crea sedes y administradores de sede. Cada sede nueva crea su esquema y sus tablas automáticamente.
- Vista de solo lectura de cada sede: resumen, estudiantes, docentes, cursos, aspirantes.
- **Monitoreo general** y, dentro de cada sede, **Horarios**, **Avances** y **Auditoría**.
- Cambio de contraseña desde **CONFIGURACIÓN**. Después de cambiarla, la nueva reemplaza a la del `.env`.

**Administrador de sede**
- Estudiantes: crear, editar, exportar e importar CSV, habilitar y deshabilitar acceso, restablecer contraseñas.
- Cursos (grupos por ciclo), materias, matrículas, plazos para subir notas.
- Aspirantes: revisión de documentos y habilitación como estudiantes.
- **Matrícula financiera** (menú propio): estado de cada estudiante, filtros por nombre, documento, curso y jornada; aprobar o rechazar con motivo.
- Notas: criterios, notas por criterio, definitiva, exportación CSV/PDF, observación del docente.

**Docente**
- Notas por criterio con plazo; observación por estudiante; hoja de vida y documentos de formación.

**Estudiante** (portal `/panel`)
- **Actualizar mis datos** y **Mi foto** (JPG o PNG, máximo 2 MB).
- **Notas**: se elige el periodo; resumen con ciclo, definitiva, veces cursada y **promedio parcial**; cada asignatura con **Ver más** (desglose por criterio).
- **Notas (PDF)**: reporte con foto, porcentajes, definitivas, observación del docente y promedio parcial.
- **Matrícula financiera**: sube recibo (PDF, JPG o PNG) por modalidad y periodo; ve el estado y el motivo si lo rechazan.

**Aspirante**
- Inscripción en dos pasos; documentos; certificado de discapacidad solo si responde "Sí".

## 6. Reglas de trabajo acordadas

- Los commits se hacen solo cuando se piden. Cada commit actualiza este resumen.
- Mensaje con la línea `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`.
- No copiar logos, nombres ni fotos de otras instituciones.
- No subir a GitHub ni `.env`, ni respaldos de la base, ni `app/uploads/`.

## 7. Pendientes

- Subir `version8` a `version11` a GitHub y crear el PR (requiere `gh auth login`).
- Revisión visual en el navegador de: inscripción, monitoreo, matrícula financiera, notas del estudiante, configuración, reporte PDF y migración. Solo se probó con pruebas automáticas.
- Probar de punta a punta el botón **Crear sede** (solo se probó la función que crea el esquema).
- Decidir si la contraseña del superadministrador se guarda como hash en la base y se quita del `.env`.
- Foto del estudiante: solo la sube el estudiante; el administrador no puede subirla.
- Reporte PDF: falta la columna de ciclo y la columna "Tipo" (CO/CE), que el sistema no guarda.
- Matrícula financiera: el monitoreo general no cuenta los recibos pendientes.
- Aspirantes: la lista no tiene filtros de curso y jornada.
- Enlaces de **Biblioteca virtual** y **Moodle** siguen en `#` (`BIBLIOTECA_URL` y `MOODLE_URL` en `blueprints/dash.py`).
- Auditoría: no registra la edición de hojas de vida de docentes ni las consultas.
- Promedio parcial: es promedio simple; si se quiere ponderado por créditos, cambiar `_promedio`.

## 8. Mapa de archivos clave

- `app.py`: arranque y registro de blueprints.
- `nucleo/db.py`: conexión PostgreSQL por esquema, `Conexion`, `get_db`, `crear_base`.
- `nucleo/sedes.py`: esquema central, sedes y administradores de sede.
- `nucleo/esquema_sede.sql`, `nucleo/esquema_central.sql`: tablas.
- `migrar_a_postgres.py`: migración de SQLite a PostgreSQL (ya ejecutada).
- `nucleo/auditoria.py`: registro de acciones por sede.
- `nucleo/seguridad.py`: roles y `requiere_rol`.
- `blueprints/auth.py`: ingreso, cuentas y **CONFIGURACIÓN**.
- `blueprints/superadmin.py`: sedes, administradores, monitoreo, horarios, avances y auditoría.
- `blueprints/admin.py`: módulo del administrador de sede.
- `blueprints/docente.py`: portal del docente.
- `blueprints/dash.py`: portal del estudiante.
- `blueprints/aspirante.py`, `blueprints/web.py`: inscripción pública y portal del aspirante.
- `servicios/notas.py`: criterios, definitivas, plazos y observaciones.
- `servicios/reporte_notas.py`: PDF de notas.
- `servicios/matricula_financiera.py`: recibos de matrícula.
- `servicios/fotos.py`: foto del estudiante.
- `servicios/estudiantes_csv.py`: exportar e importar estudiantes.
- `templates/_filtros.html`: barra de filtros común.
- `templates/_notas_curso.html`: tabla de notas compartida por docente y administrador.
