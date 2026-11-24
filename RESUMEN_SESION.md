# Resumen para continuar en Linux

Este archivo resume lo que se construyó en la sesión de desarrollo para que se pueda seguir en otro equipo.

## 1. Estado de Git

| Rama | Commit | Contenido | Subida a GitHub |
|---|---|---|---|
| `version7` | `02b0ced` | Base anterior (notas, aspirantes, docentes) | Sí |
| `version8` | `9800e98` | Multi-sede, superadministrador, inscripción en dos pasos, CSV de estudiantes, plazos de notas | No |
| `version9` | `b4112fe` | Monitoreo general, auditoría por sede, matrícula financiera (recibos) | No |
| `version10` | `0ef780c` | Notas por periodo con ciclo, promedio parcial, PDF de notas con foto y observaciones, foto del estudiante, filtros, cambio de contraseña | Sí |
| `version11` | `46d02c7` | Migración de SQLite a PostgreSQL (sección 3) | Sí |
| `version12` | `4530a35` | Finanzas por sede: perfil financiero, administradora financiera, bitácora de accesos, kárdex y bajas (sección 5) | Sí |
| `version13` | `9e7f9b9` | Sedes y administradores de sede en ventanas de creación, igual que en finanzas | Sí (PR #11) |
| `version14` | (este commit) | Puesta en marcha en Linux (sección 2) y notas para migrar al servidor (sección 9) | No |

El PR de `version10` no se ha creado: `gh` no está autenticado en el equipo de Windows (`gh auth login`).

## 2. Cómo pasar al equipo Linux

1. **Código:** `git clone https://github.com/juan-sotelo1994/Plataforma-1.git` y `git checkout version13`.
2. **PostgreSQL** en Linux (por ejemplo `sudo apt install postgresql`). Crear el usuario `instituto_app` y la base `instituto` con dueño `instituto_app`.
3. **Datos:** copiar a mano el respaldo `app/instance/instituto.dump` (no está en GitHub porque contiene datos personales y contraseñas cifradas) y restaurarlo:
   ```bash
   pg_restore --no-owner --role=instituto_app -d instituto instituto.dump
   ```
4. **Archivos que no viajan por Git** (copiar a mano):
   - `app/.env`: `SECRET_KEY`, `DEV_CORREO`, `DEV_CONTRASENA` y `DATABASE_URL`. No subirlo a GitHub.
   - `app/uploads/`: documentos, recibos de matrícula, hojas de vida y fotos de estudiantes.
   - Las bases SQLite (`app/instance/*.db`) ya no se usan: son solo respaldo.

### Lo que pasó al montarlo en Linux (equipo de desarrollo, noviembre 2026)

- **Python sin `venv`:** Ubuntu no trae `ensurepip`. Instalar antes `sudo apt install python3.14-venv` (o la versión de Python que tenga el equipo). Si no se puede, se crea con `python3 -m venv --without-pip .venv` y se instala con `pip3 install --prefix .venv --ignore-installed -r requirements.txt`.
- **El venv vive en `app/.venv`** (ignorado por Git). Ejecutar siempre con `app/.venv/bin/python`, no con `/usr/bin/python3`, o sale `No module named 'flask'`. En VS Code, elegir ese intérprete con "Python: Select Interpreter".
- **`Falta DATABASE_URL en app/.env`:** el `.env` se copió sin esa línea. Agregarla con el formato de la sección 3.
- **`la autentificación password falló para el usuario «instituto_app»`:** el PostgreSQL nuevo no trae los usuarios del otro equipo. Hay que crear `instituto_app` (o cambiarle la clave) para que coincida con `DATABASE_URL`:
  ```bash
  sudo -u postgres psql -c "ALTER ROLE instituto_app WITH LOGIN PASSWORD 'CLAVE';"
  ```
- **Base restaurada con dueño `postgres`:** si el respaldo se restaura como `postgres`, `instituto_app` no es dueño de la base, de los esquemas `central` y `sede_*` ni de sus tablas, y no puede crear sedes nuevas. Hay que pasarle la propiedad (`ALTER DATABASE instituto OWNER TO instituto_app`, y `ALTER SCHEMA` / `ALTER TABLE ... OWNER TO instituto_app` en cada esquema), o restaurar desde el principio con `--role=instituto_app`.
- **Correo del superadministrador:** no está en ninguna tabla; es `DEV_CORREO` del `.env`. La tabla `central.credencial_superadmin` solo guarda el hash si se cambió la clave desde CONFIGURACIÓN (si está vacía, vale `DEV_CONTRASENA`). Para averiguar qué correo se usaba:
  ```sql
  SELECT usuario, count(*) FROM central.auditoria_financieros GROUP BY usuario;
  ```
- **El `.env` solo se lee al arrancar:** después de cambiarlo hay que detener la app (Ctrl+C) y lanzarla de nuevo. Si sale `Port 5712 is in use`, ya hay otra copia corriendo: detenerla primero (`ps -ef | grep app.py` y `kill <pid>`).
- **No abrir el `.env` en dos nanos a la vez:** el que se guarde último pisa los cambios del otro.

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
- **Finanzas** (`/superadmin/finanzas`): indicadores de todas las sedes; saldos por sede (con **Ver**, solo lectura: ingresos, egresos, gastos operacionales, bajas y matrícula financiera); movimientos y bajas de todas las sedes con filtros; bitácora de accesos.
- Crea, edita, bloquea y quita **usuarios financieros** (cada uno asignado a una sede) y **administradoras financieras** (ven todas las sedes en solo lectura). Todo queda en la bitácora de accesos.
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

**Financiero** (portal `/finanzas`, una sola sede asignada)
- Cuentas de ingreso y de egreso (se crean con siete cuentas iniciales), movimientos con anulación con motivo, kárdex de artículos con costo promedio, bajas que descuentan del kárdex.
- Un usuario bloqueado no ingresa y su sesión abierta se cierra en su siguiente acción.

**Administradora financiera** (portal `/finanzas-admin`, solo lectura)
- Ve las cuentas de los financieros de todas las sedes y las finanzas de cada sede. Cada ingreso y cada consulta queda en la bitácora.

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

- Crear el PR de `version14`.
- Preparar los archivos de despliegue para el servidor (sección 9): gunicorn, servicio de systemd, Nginx y respaldo diario.
- Finanzas: los pagos de pensión por estudiante no están conectados con los recibos de matrícula; el ingreso se registra a mano.
- Finanzas: no hay forma de reasignar la sede de un usuario desde el portal financiero; se hace desde el superadministrador con **Editar**.
- Finanzas: revisión visual en el navegador de las pantallas nuevas (solo se probó con pruebas automáticas).
- Finanzas: las cuentas `cuentas@gmail.com` y `contadora.ipiales@gmail.com` tienen contraseña inicial de prueba; deben cambiarla desde CONFIGURACIÓN.
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

- Inicio de sesión con Google (inscripción): las credenciales ya están en `app/.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`). Falta agregar en Google Cloud la URI `http://127.0.0.1:5712/inscripcion/google/respuesta` y decidir el estado de la pantalla de consentimiento. Regenerar el secreto (apareció en el chat).
- App Flutter y API `/api/v1`: planeado, no iniciado. Antes hay que publicar el sistema en un servidor con HTTPS (nginx + gunicorn, `ProxyFix`, `FLASK_DEBUG=0`).

## 8. Mapa de archivos clave

- `app.py`: arranque y registro de blueprints.
- `nucleo/db.py`: conexión PostgreSQL por esquema, `Conexion`, `get_db`, `crear_base`.
- `nucleo/sedes.py`: esquema central, sedes y administradores de sede.
- `nucleo/esquema_sede.sql`, `nucleo/esquema_central.sql`: tablas.
- `migrar_a_postgres.py`: migración de SQLite a PostgreSQL (ya ejecutada).
- `nucleo/auditoria.py`: registro de acciones por sede.
- `nucleo/seguridad.py`: roles y `requiere_rol`.
- `blueprints/auth.py`: ingreso, cuentas y **CONFIGURACIÓN**.
- `blueprints/superadmin.py`: sedes, administradores, monitoreo, horarios, avances, auditoría y finanzas del superadministrador.
- `blueprints/finanzas.py`: portal del financiero (una sede).
- `blueprints/finanzas_admin.py`: portal de la administradora financiera (solo lectura).
- `servicios/finanzas.py`: cuentas, movimientos, kárdex, bajas e indicadores de finanzas.
- `templates/superadmin/_finanzas_sede_contenido.html`: vista de finanzas por sede, compartida por superadmin y administradora.
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

## 9. Migración al servidor (producción)

Es el mismo procedimiento de la sección 2, con estos cambios para que sea seguro y no dependa de una terminal abierta.

### Igual que en desarrollo
1. `git clone` del repositorio.
2. PostgreSQL: crear `instituto_app` y la base `instituto` con dueño `instituto_app`, y restaurar `instituto.dump` **directamente con ese usuario** para no tener que corregir dueños después:
   ```bash
   pg_restore --no-owner --role=instituto_app -h localhost -U instituto_app -d instituto instituto.dump
   ```
3. Instalar `python3-venv` antes de crear `app/.venv`, y luego `pip install -r requirements.txt`.
4. Crear `app/.env` (`SECRET_KEY`, `DEV_CORREO`, `DEV_CONTRASENA`, `DATABASE_URL`).
5. Copiar `app/uploads/`.

### Lo que cambia en el servidor
- **Claves fuertes:** clave larga para `instituto_app` y para el superadministrador, y una `SECRET_KEY` nueva (`python3 -c "import secrets; print(secrets.token_hex(32))"`). Nunca reutilizar las de desarrollo.
- **`FLASK_DEBUG=0`** en el `.env`. Con debug activo, una página de error permite ejecutar código en el servidor.
- **No usar `python app.py`** (es el servidor de desarrollo). Usar **gunicorn** (agregarlo a `requirements.txt`), escuchando solo en `127.0.0.1`.
- **Servicio de systemd** (`plataforma.service`): la app arranca sola con el servidor y se reinicia si se cae. Para aplicar cambios del `.env`: `sudo systemctl restart plataforma`.
- **Nginx delante de la app** con **HTTPS (Let's Encrypt / certbot)**. Nginx sirve `static/` y reenvía el resto a gunicorn. Ajustar `client_max_body_size 12M` (la app acepta subidas de hasta 12 MB).
- **Firewall (ufw):** abrir solo SSH, 80 y 443. PostgreSQL (5432) y la app (5712) quedan cerrados al exterior.
- **Respaldos automáticos:** `pg_dump -Fc` diario de `instituto` y copia de `app/uploads/`, guardados fuera del servidor.
- **Superadministrador:** después del primer ingreso, cambiar la clave desde **CONFIGURACIÓN** para que quede cifrada en `central.credencial_superadmin` y no dependa del texto claro del `.env`.
- **Permisos del `.env`:** `chmod 600 app/.env`, con dueño el usuario del sistema que corre la app.

### Datos que hay que tener a mano
- Sistema operativo del servidor (por ejemplo Ubuntu 24.04) y versión de Python.
- Dominio y acceso a su DNS (para HTTPS).
- El respaldo más reciente `instituto.dump` y la carpeta `app/uploads/`.
