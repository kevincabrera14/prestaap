# 💰 PrestApp — Sistema de Gestión de Préstamos y Cobros

Plataforma web para administrar préstamos "gota a gota" (cobro diario, semanal, quincenal o mensual): control de rutas de cobro, tarjetas de crédito por cliente, abonos, caja por ruta, gastos, reportes financieros y geolocalización de clientes — con un asistente de IA integrado para resolver dudas de uso en tiempo real.

**🔗 Demo en vivo:** [web-production-2d2a9.up.railway.app](https://web-production-2d2a9.up.railway.app/)


## ✨ Características principales

- **Rutas de cobro**: cada ruta tiene su propia caja (base de dinero disponible), su supervisor y los trabajadores/cobradores asignados.
- **Tarjetas de préstamo**: registro del cliente (identificación, nombre, contacto), monto base, tasa de interés y frecuencia de cobro (diario, semanal, quincenal o mensual). Al crear una tarjeta, el sistema genera automáticamente el plan de cuotas y descuenta el monto de la base de la ruta — **validando que haya fondos suficientes** antes de aprobar el préstamo.
- **Abonos en cascada**: cada pago se aplica primero a la cuota pendiente más antigua; cuando el saldo llega a cero, la tarjeta pasa a estado *Pagada* automáticamente.
- **Estados y alertas visuales**: cada tarjeta muestra si el cliente ya pagó hoy (verde), está en mora (rojo) o sigue al día, calculado según su frecuencia de cobro.
- **Caja y movimientos por ruta**: ingresos de capital, gastos de operación (registrados por los propios trabajadores) y retiros justificados, todo con historial y trazabilidad.
- **Reportes**: reporte diario y por rango de fechas, historial de caja, historial financiero por ruta.
- **Mapa de clientes con validación GPS**: ubicación geográfica de cada cliente en un mapa, con verificación de coordenadas al registrar la visita.
- **Renovación de crédito**: permite otorgar un nuevo préstamo a un cliente existente sin perder su historial.
- **Cierre de caja automático**: un job programado (cron en Railway) cierra las cajas de todas las rutas todos los días.
- **Asistente de IA "PrestAyuda"**: chat integrado (Groq Cloud + Llama 3.3) que responde dudas de uso basado en la interfaz real de la app, con un tono cercano y práctico para el cobrador en la calle.
- **Acceso por roles** (Administrador / Supervisor / Trabajador), cada uno con su propio panel y permisos.

## 👥 Roles del sistema

| Rol | Puede hacer |
|---|---|
| **Trabajador** (asesor/cobrador) | Ver solo las rutas que tiene asignadas, registrar abonos, consultar su historial de cobros del día, registrar gastos |
| **Supervisor** | Todo lo del Trabajador en sus rutas + crear/editar rutas, crear y renovar tarjetas, ingresar capital, ver reportes financieros y auditar cajas |
| **Administrador** | Acceso total: todas las rutas, todos los usuarios, configuración global del sistema |

Si un usuario intenta entrar a una vista que no corresponde a su rol, el sistema bloquea el acceso con el mensaje *"No tienes permiso para acceder aquí"* y lo redirige automáticamente.

## 🛠️ Stack tecnológico

| Área | Tecnología |
|---|---|
| Backend | Python 3, Django 6.0 |
| Base de datos | PostgreSQL en producción (Railway) · SQLite en desarrollo |
| Servidor de aplicación | Gunicorn |
| Archivos estáticos | WhiteNoise |
| Asistente de IA | Groq Cloud (Llama 3.3) |
| Frontend | Templates de Django, CSS, JavaScript |
| Geolocalización | API de geolocalización del navegador + mapa de clientes |
| Despliegue | Railway (con `release` command y cron job diario) |

## 🏗️ Estructura del proyecto

```
├── app/
│   ├── models.py            # Perfil, Ruta, Targeta, Cuota, Abono, CajaRuta, MovimientoRuta, GastoTrabajador, HistorialRuta
│   ├── views.py              # Dashboards por rol, CRUD de rutas/tarjetas, abonos, reportes, mapa, asistente IA
│   ├── permissions.py         # Decoradores solo_admin / supervisor_required / solo_trabajador
│   ├── admin.py
│   ├── signals.py
│   ├── management/commands/
│   │   └── cerrar_cajas.py    # Cierre automático de caja (ejecutado por cron en Railway)
│   ├── migrations/
│   ├── static/
│   │   ├── css/                # style.css
│   │   ├── img/                # logo, favicon, ícono del asistente IA
│   │   └── js/                 # js.js
│   └── templates/app/
│       ├── base.html, inicio.html, login.html, informacion.html
│       ├── admin.html, supervisor.html, trabajador.html
│       ├── crear_ruta.html, editar_ruta.html, eliminar_ruta.html
│       ├── crear_targeta.html, editar_targeta.html, eliminar_targeta.html, renovar_targeta.html
│       ├── crear_abono.html, historial_abonos.html, lista_abonos.html
│       ├── agregar_capital.html, agregar_gasto.html, registrar_gasto.html
│       ├── historial_cajas.html, historial_ruta.html, historial_trabajador.html
│       ├── reporte_diario.html, reporte_rango.html
│       ├── mapa_clientes.html, validar_gps.html
│       └── clientes_finalizados.html
├── config/                   # Configuración del proyecto (settings, urls, wsgi/asgi)
├── staticfiles/               # Archivos estáticos recolectados para producción
├── manage.py
├── Procfile                  # release: migrate + collectstatic · web: gunicorn
├── railway.json               # Cron diario para cierre de cajas
└── requirements.txt
```

## ⚙️ Instalación local

```bash
# 1. Clonar el repositorio
git clone https://github.com/kevincabrera14/prestaap.git
cd prestaap

# 2. Crear y activar entorno virtual
python -m venv venv
source venv/bin/activate      # En Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
# Crea un archivo .env en la raíz con:
#   SECRET_KEY=tu-clave-secreta
#   GROQ_API_KEY=tu-clave-de-groq   (opcional, solo para el asistente de IA)

# 5. Aplicar migraciones
python manage.py migrate

# 6. Crear un superusuario para entrar como administrador
python manage.py createsuperuser

# 7. Iniciar el servidor de desarrollo
python manage.py runserver
```

La aplicación quedará disponible en `http://127.0.0.1:8000/`.

## 🔑 Variables de entorno

| Variable | Descripción |
|---|---|
| `SECRET_KEY` | Clave secreta de Django. Genera una propia para producción |
| `DATABASE_URL` | Cadena de conexión a PostgreSQL (Railway la provee automáticamente) |
| `GROQ_API_KEY` | Clave de Groq Cloud para el asistente "PrestAyuda". Si no está configurada, el resto de la app funciona igual; solo el chat de IA muestra un mensaje de error |
| `RAILWAY_ENVIRONMENT` | Variable que Railway define automáticamente; se usa para desactivar `DEBUG` en producción |

## 🚀 Despliegue

Desplegado en [Railway](https://railway.app/) con PostgreSQL. El `Procfile` ejecuta migraciones y recolecta estáticos antes de levantar el servidor:

```
release: python manage.py migrate && python manage.py collectstatic --noinput
web: gunicorn config.wsgi:application
```

Además, `railway.json` programa un cron diario a las 23:59 que ejecuta `python manage.py cerrar_cajas`, cerrando automáticamente la caja de todas las rutas al final del día.

## ✍️ Autor

**Kevin Cabrera**
(https://github.com/kevincabrera14) · ka5849698@gmail.com
