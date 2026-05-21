# 📘 Manual de Usuario - PrestApp
*Sistema de Gestión de Préstamos y Cobros*

---

## 1. Introducción a PrestApp
**PrestApp** es una plataforma web centralizada para la gestión avanzada de préstamos y cobros periódicos. El sistema está diseñado para controlar de extremo a extremo el flujo de caja de diferentes rutas o zonas, automatizar el cálculo y distribución de cuotas, y supervisar el rendimiento de los cobradores en campo en tiempo real.

---

## 2. Roles y Permisos del Sistema
El acceso a las funcionalidades de PrestApp está restringido mediante un sistema estricto de permisos en el backend. Existen tres perfiles definidos:

*   **Administrador (ADMIN):** Posee acceso total e irrestricto a la base de datos global del sistema. Puede auditar todas las rutas, modificar configuraciones globales y gestionar usuarios de cualquier nivel.
*   **Supervisor:** Encargado de la gestión operativa de una o varias rutas específicas. Tiene acceso al **Panel Supervisor** (`/dashboard/supervisor/`) donde puede crear rutas, gestionar tarjetas de préstamo, inyectar capital base, registrar gastos y auditar reportes financieros.
*   **Trabajador (Asesor / Cobrador):** Operador de campo enfocado exclusivamente en la recaudación. Tiene acceso al **Panel Trabajador** (`/dashboard/trabajador/`), donde visualiza únicamente las rutas que tiene asignadas, permitiéndole registrar abonos y consultar su historial de cobros del día.

> 🔒 **Seguridad:** Si un usuario intenta forzar el ingreso a una vista que no corresponde a su rol, el sistema bloqueará la acción con el mensaje *"No tienes permiso para acceder aquí"* y lo redirigirá automáticamente.

---

## 3. Guía de Operación Paso a Paso

### 💵 A. Apertura y Gestión de Capital Base
Este proceso permite cargar dinero a la caja general de una ruta para que los asesores puedan otorgar préstamos o cubrir gastos.

1. Inicie sesión y diríjase al **Panel Supervisor** (`/dashboard/supervisor/`).
2. En la barra superior, seleccione la **Ruta** con la que desea trabajar.
3. En el menú de acciones, haga clic en el botón **"Ingreso de capital"** (esto lo llevará a la pantalla `/ruta/<ruta_id>/capital/`).
4. Complete los campos del formulario:
    *   **Monto a agregar:** Ingrese el valor numérico (admite decimales).
    *   **Observación:** Breve nota que justifique el movimiento (ej. *Carga inicial de semana*).
5. Haga clic en el botón 💵 **Agregar Capital**.

> ⚠️ **¡Atención!** El sistema validará que el monto sea estrictamente mayor a cero. De lo contrario, rechazará la transacción con la alerta: *"El monto debe ser mayor a cero."*

---

### 👤 B. Registro de Clientes y Creación de Tarjetas de Préstamo
Flujo para dar de alta a un deudor y asignarle un plan de pagos automático.

1. Desde el **Panel Supervisor**, seleccione **"Nueva tarjeta"** (`/targetas/crear/`).
2. Rellene la información requerida en el formulario:
    *   **Ruta Asignada:** Seleccione la zona correspondiente.
    *   **Datos del Cliente:** Tipo de documento, Número de identificación y Nombre completo (campos obligatorios). Teléfono, Dirección y observaciones son opcionales.
    *   **Condiciones del Crédito:** Defina la **Frecuencia de cobro** (*DIARIO, SEMANAL, QUINCENAL, MENSUAL*), el **Monto Base**, la **Tasa de Interés (%)** y el **Plazo (Días)**.
3. Presione el botón **Crear Tarjeta**.

> ⚠️ **Regla de Negocio Crítica:** El sistema verificará que la ruta tenga suficiente dinero líquido en su base. Si intenta prestar más de lo que hay en caja, el sistema bloqueará el registro mostrando el error: *"Base insuficiente en la ruta. Saldo actual: $X"*. Al aprobarse, el capital se descuenta de la ruta y las cuotas se generan automáticamente en cascada.

---

### 📉 C. Registro de Abonos (Cobros de Cuotas)
Procedimiento para asentar los pagos diarios o periódicos realizados por los clientes.

1. Desde el listado de tarjetas (en el panel de Supervisor o de Trabajador), ubique al cliente y haga clic en 💵 **Abonar** (`/targetas/<targeta_id>/abonar/`).
2. **Selección de Cuota:** El sistema seleccionará por defecto la cuota pendiente más antigua. Puede cambiarla manualmente si el cliente desea abonar a una cuota específica.
3. En el campo **Monto a recibir**, digite la cantidad entregada por el cliente.
4. Haga clic en 💵 **Confirmar registro**.

#### ¿Qué pasa en el backend al confirmar?
*   El dinero ingresado se distribuye de forma automática comenzando por las deudas más viejas.
*   Cuando una cuota llega a `$0` pendientes, su estado cambia automáticamente a **PAGADA**.
*   El dinero se suma de inmediato a la base líquida de la ruta (`ruta.base`) y se genera un movimiento de **INGRESO**.

---

## 4. Estados del Préstamo y Alertas Visuales

Para facilitar la auditoría rápida en calle o desde la oficina, el sistema utiliza un código de estados y colores automatizado:

| Elemento / Campo | Estado / Valor | Significado Operativo |
| :--- | :--- | :--- |
| **Tarjeta.estado** | `PAGO` (Al día) | El crédito está activo, tiene saldo pendiente, pero el cliente no presenta retrasos en sus cuotas. |
| **Tarjeta.estado** | `MORA` (En mora) | El cliente cuenta con una o más cuotas cuya fecha de vencimiento es anterior a la fecha de hoy y no han sido liquidadas. |
| **Tarjeta.estado** | `PAGADA` | El saldo del crédito ha llegado a `$0`. El préstamo se da por finalizado con éxito. |
| **Clase UI** | `pago-hoy` (Fondo Verde) | Indica visualmente en el listado que este cliente ya realizó un abono el día de hoy. |
| **Clase UI** | `cobro-atrasado` (Fondo Rojo) | Muestra un banner de advertencia indicando los días exactos que el cliente lleva sin reportar pagos. |

---

## 5. Preguntas Frecuentes y Solución de Errores

### ❌ Error: "Base insuficiente en la ruta" al crear un préstamo.
*   **Causa:** No hay suficiente dinero físico o registrado en la base de esa ruta para cubrir el desembolso.
*   **Solución:** Un supervisor debe ingresar primero al módulo de **Ingreso de Capital** de esa ruta, registrar una recarga monetaria positiva y luego proceder a crear la tarjeta del cliente.

### ❌ Error: "No hay cuotas pendientes para registrar el abono..."
*   **Causa:** El usuario está intentando meter un pago a una tarjeta que ya fue liquidada en su totalidad o cuyas cuotas ya están en `$0`.
*   **Solución:** Verifique el saldo de la tarjeta. Si el saldo restante es `0`, el crédito ya finalizó y no requiere más transacciones.

### ❌ Error: "Fondos insuficientes. La base actual es $X" al meter un gasto.
*   **Causa:** Los gastos de ruta (como gasolina, viáticos, etc.) se restan directamente del efectivo de la ruta (`ruta.base`). No puedes registrar un gasto mayor al dinero que hay en caja.
*   **Solución:** Validar si hay cobros del día que falten por registrar (lo que subirá la base) o inyectar capital de respaldo.