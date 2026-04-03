#views 
# =====================================================
# import
# =====================================================

from django.utils.timezone import localtime, make_aware, get_current_timezone, localdate, now
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .permissions import supervisor_required
from .models import Ruta, Targeta, Abono, MovimientoRuta, CajaRuta, Cuota
from django.contrib import messages
from django.db.models import Sum, Q, F
from decimal import Decimal
import datetime
from django.utils import timezone
from django.utils.timezone import localtime, localdate, make_aware

from django.http import HttpResponse
from django.contrib.auth.decorators import user_passes_test
from .models import Cuota

from django.urls import reverse

# =====================================================
# AUTH
# =====================================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password")
        )
        if user:
            login(request, user)
            return redirect('dashboard')

    return render(request, "app/login.html")


@login_required
def cerrar_sesion(request):
    logout(request)
    return redirect('login')


# =====================================================
# DASHBOARD CENTRAL
# =====================================================

@login_required(login_url='login')
def dashboard(request):
    try:
        rol = request.user.perfil.rol
    except Exception:
        logout(request)
        return redirect('login')

    if rol == 'ADMIN':
        return redirect('dashboard_admin')
    if rol == 'SUPERVISOR':
        return redirect('dashboard_supervisor')
    if rol == 'TRABAJADOR':
        return redirect('dashboard_trabajador')

    logout(request)
    return redirect('login')


# =====================================================
# ADMIN
# =====================================================

@login_required
def dashboard_admin(request):
    rutas = Ruta.objects.select_related('supervisor').prefetch_related('trabajadores')
    return render(request, 'app/admin.html', {'rutas': rutas})


# =====================================================
# SUPERVISOR
# =====================================================
from django.db.models import Q # Importante añadir esta importación al inicio

from django.db.models import Q # Importante añadir esta importación al inicio
@login_required
@supervisor_required
def dashboard_supervisor(request):
    # Solo mostramos las rutas que pertenecen al supervisor actual
    rutas = Ruta.objects.filter(supervisor=request.user)
    
    ruta_sel = None
    targetas = []

    resumen = {
        "total_clientes": 0,
        "en_mora": 0,
        "base": 0,
        "dinero_en_ruta": 0,
    }

    ruta_id = request.GET.get("ruta")
    q = request.GET.get("q")

    if ruta_id:
        # Validamos que la ruta seleccionada también pertenezca al supervisor
        ruta_sel = get_object_or_404(Ruta, id=ruta_id, supervisor=request.user)

        # 1. Traemos las tarjetas que NO estén marcadas como PAGADA explícitamente
        query = Targeta.objects.filter(ruta=ruta_sel).exclude(estado='PAGADA')

        if q:
            query = query.filter(nombre_cliente__icontains=q)

        # 2. FILTRO DE PYTHON: Excluimos las que tengan saldo 0 aunque no digan "PAGADA"
        targetas_raw = [t for t in query if t.saldo_restante > 0]

        # 3. Anotamos cuotas pagadas y total para el badge del template
        targetas = []
        for t in targetas_raw:
            t.cuotas_pagadas = t.cuotas.filter(estado='PAGADA').count()
            t.total_cuotas = t.cuotas.count()
            targetas.append(t)

        # =========================
        # RESUMEN FINANCIERO REAL
        # =========================

        resumen["total_clientes"] = len(targetas)

        # Contamos los que están en mora dentro de nuestra lista filtrada
        resumen["en_mora"] = len([t for t in targetas if t.estado == "MORA"])

        resumen["base"] = ruta_sel.base

        # Sumamos el saldo restante de la lista final
        resumen["dinero_en_ruta"] = sum(t.saldo_restante for t in targetas)

    context = {
        "rutas": rutas,
        "ruta_sel": ruta_sel,
        "targetas": targetas,
        "resumen": resumen,
    }

    return render(request, "app/supervisor.html", context)
# =====================================================
# ruta
# =====================================================


@login_required
@supervisor_required
def crear_ruta(request):
    if request.method == "POST":
        Ruta.objects.create(
            nombre=request.POST.get("nombre"),
            base=Decimal(request.POST.get("base")),
            supervisor=request.user
        )
        messages.success(request, "Ruta creada correctamente")
        return redirect('dashboard_supervisor')

    return render(request, "app/crear_ruta.html")



@login_required
@supervisor_required
def editar_ruta(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id, supervisor=request.user)

    if request.method == "POST":
        ruta.nombre = request.POST.get("nombre")
        ruta.activa = bool(request.POST.get("activa"))
        ruta.save()
        messages.success(request, "Ruta actualizada")
        return redirect('dashboard_supervisor')

    return render(request, "app/editar_ruta.html", {"ruta": ruta})


@login_required
@supervisor_required
def eliminar_ruta(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id, supervisor=request.user)
    ruta.delete()
    messages.success(request, "Ruta eliminada")
    return redirect('dashboard_supervisor')


@login_required
@supervisor_required
def crear_targeta(request):
    rutas = Ruta.objects.filter(supervisor=request.user)

    if request.method == "POST":
        ruta_id = request.POST.get("ruta")
        monto_base = request.POST.get("monto_base")
        tasa_interes = request.POST.get("tasa_interes")
        plazo_dias = request.POST.get("plazo_dias")

        # Validación de campos
        if not all([ruta_id, monto_base, tasa_interes, plazo_dias]):
            messages.error(request, "Todos los campos obligatorios deben ser completados")
            return redirect(request.path)

        ruta = get_object_or_404(Ruta, id=ruta_id)

        try:
            monto = Decimal(monto_base)
            tasa = int(tasa_interes)
            plazo = int(plazo_dias)
        except (ValueError, TypeError):
            messages.error(request, "Los valores numéricos no son válidos")
            return redirect(request.path)

        # Validar si hay dinero suficiente en la caja de la ruta
        if monto > ruta.base:
            messages.error(request, f"Base insuficiente en la ruta. Saldo actual: ${ruta.base}")
            return redirect(f"{request.path}?ruta={ruta_id}")

        # Descontar de la base y registrar
        ruta.base -= monto
        ruta.save(update_fields=['base'])

        targeta = Targeta.objects.create(
            ruta=ruta,
            tipo_identificacion=request.POST.get("tipo_identificacion"),
            numero_identificacion=request.POST.get("numero_identificacion"),
            nombre_cliente=request.POST.get("nombre_cliente"),
            telefono=request.POST.get("telefono"),
            direccion_casa=request.POST.get("direccion_casa"),
            direccion_negocio=request.POST.get("direccion_negocio"),
            observaciones=request.POST.get("observaciones"),
            monto_base=monto,
            tasa_interes=tasa,
            plazo_dias=plazo,
            creada_por=request.user
        )

        # Generar las cuotas
        crear_cuotas(targeta)

        # Registrar el movimiento de salida de dinero
        MovimientoRuta.objects.create(
            ruta=ruta,
            tipo='EGRESO',
            monto=monto,
            descripcion=f'Préstamo otorgado a {targeta.nombre_cliente}'
        )

        messages.success(request, "Tarjeta creada correctamente")
        
        # Redirigir al dashboard filtrando por la ruta seleccionada
        return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

    return render(request, 'app/crear_targeta.html', {
        'rutas': rutas
    })


@login_required
@supervisor_required
def editar_targeta(request, targeta_id):
    # Obtenemos la tarjeta asegurando que pertenece a una ruta del supervisor actual
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    rutas = Ruta.objects.filter(supervisor=request.user)

    if request.method == "POST":
        try:
            # 1. Actualizar la Ruta (si cambió)
            nueva_ruta_id = request.POST.get("ruta")
            if nueva_ruta_id:
                targeta.ruta_id = int(nueva_ruta_id)

            # 2. Actualizar campos de texto y básicos usando setattr
            campos_texto = [
                "tipo_identificacion", "numero_identificacion", "nombre_cliente",
                "telefono", "direccion_casa", "direccion_negocio", "observaciones"
            ]
            for campo in campos_texto:
                valor = request.POST.get(campo)
                setattr(targeta, campo, valor)

            # 3. Actualizar campos numéricos (convertir a tipo correcto)
            targeta.tasa_interes = int(request.POST.get("tasa_interes", targeta.tasa_interes))
            targeta.plazo_dias = int(request.POST.get("plazo_dias", targeta.plazo_dias))
            
            # Manejo del Monto Base y recalcular Total
            monto_base_post = request.POST.get("monto_base")
            if monto_base_post:
                targeta.monto_base = Decimal(monto_base_post)
                # Recalculamos el monto total (base + intereses)
                interes_decimal = Decimal(targeta.tasa_interes) / 100
                targeta.monto_total = targeta.monto_base + (targeta.monto_base * interes_decimal)
                # Nota: Si ya existen abonos, el saldo_restante debería recalcularse 
                # restando los abonos existentes al nuevo monto_total.

            # 4. Guardar cambios
            targeta.save()
            messages.success(request, f"¡Tarjeta de {targeta.nombre_cliente} actualizada correctamente!")
            
            # Redirigir al dashboard con el filtro de la ruta activa
            return redirect(f"/dashboard/supervisor/?ruta={targeta.ruta.id}")

        except Exception as e:
            messages.error(request, f"Error al actualizar: {str(e)}")
            return redirect(request.path)

    return render(request, "app/editar_targeta.html", {
        "targeta": targeta,
        "rutas": rutas
    })

@login_required
@supervisor_required
def eliminar_targeta(request, targeta_id):
    # Obtenemos la tarjeta validando que sea del supervisor actual
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    ruta = targeta.ruta
    saldo_perdido = targeta.saldo_restante # Lo que el cliente aún debía
    nombre_cliente = targeta.nombre_cliente

    try:
        with transaction.atomic():
            # 1. Si la tarjeta tenía saldo pendiente, registramos el Egreso en la auditoría
            # Nota: No restamos de ruta.base porque ese dinero YA salió cuando se creó la tarjeta.
            # Solo lo marcamos como EGRESO para que aparezca en el reporte diario como "Dinero que sale de circulación".
            if saldo_perdido > 0:
                MovimientoRuta.objects.create(
                    ruta=ruta,
                    tipo='EGRESO',
                    monto=saldo_perdido,
                    descripcion=f"ELIMINACIÓN TARJETA (Pérdida) - Cliente: {nombre_cliente}"
                )

            # 2. Borramos la tarjeta (esto borrará sus cuotas y abonos en cascada si está configurado en models)
            targeta.delete()

        messages.success(request, f"Tarjeta de {nombre_cliente} eliminada. Se registró un egreso de ${saldo_perdido} por saldo pendiente.")
    except Exception as e:
        messages.error(request, f"Error al eliminar la tarjeta: {str(e)}")

    return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

# =====================================================
# TRABAJADOR
# =====================================================

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q

@login_required
def dashboard_trabajador(request):
    # Obtenemos las rutas del usuario
    rutas = Ruta.objects.filter(trabajadores=request.user)
    
    # Filtramos las tarjetas base
    targetas = Targeta.objects.filter(ruta__in=rutas)

    # Captura de filtros desde el GET
    q = request.GET.get("q")
    estado = request.GET.get("estado")
    ruta_id = request.GET.get("ruta")

    # Aplicación de filtros
    if q:
        targetas = targetas.filter(nombre_cliente__icontains=q)
    if estado:
        targetas = targetas.filter(estado=estado)
    if ruta_id:
        targetas = targetas.filter(ruta_id=ruta_id)

    # --- OPTIMIZACIÓN Y CÁLCULO DE CUOTAS ---
    # Usamos prefetch_related para traer las cuotas de una sola vez y evitar lentitud
    targetas = targetas.prefetch_related('cuotas')

    for t in targetas:
        # Esto ahora se ejecuta en memoria gracias al prefetch_related
        todas_las_cuotas = t.cuotas.all()
        t.cuotas_pagadas = sum(1 for c in todas_las_cuotas if c.estado == 'PAGADA')
        t.total_cuotas = len(todas_las_cuotas)

    # Resumen estadístico
    resumen = {
        "total_clientes": targetas.count(),
        "en_mora": targetas.filter(estado="MORA").count(),
        # Usamos una lista de comprensión para el saldo (más rápido en Python que sum() con generador)
        "total_saldo": sum([t.saldo_restante for t in targetas]),
    }

    return render(request, "app/trabajador.html", {
        "rutas": rutas,
        "targetas": targetas,
        "resumen": resumen,
        "ruta_sel": Ruta.objects.filter(id=ruta_id).first() if ruta_id else None,
    })
# =====================================================
# ABONOS
# =====================================================

@login_required
@supervisor_required
def lista_abonos(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    abonos = targeta.abonos.all().order_by('-fecha')

    return render(request, 'app/lista_abonos.html', {
        'targeta': targeta,
        'abonos': abonos
    })




@login_required
def crear_abono(request, targeta_id=None):
    # 1. Identificación de la tarjeta
    if not targeta_id:
        targeta_id = request.POST.get("targeta") or request.GET.get("targeta")
    
    targeta = None
    cuotas_pendientes = []
    if targeta_id:
        targeta = get_object_or_404(Targeta, id=targeta_id)
        cuotas_pendientes = targeta.cuotas.filter(estado='PENDIENTE').order_by('numero')

    if request.method == "POST" and targeta:
        cuota_id = request.POST.get("cuota")
        monto_input = request.POST.get("monto_abono")

        # --- BLOQUE DE DETECCIÓN AUTOMÁTICA ---
        try:
            monto_recibido = Decimal(monto_input) if monto_input and Decimal(monto_input) > 0 else Decimal(0)
        except (ValueError, TypeError, Decimal.InvalidOperation):
            monto_recibido = Decimal(0)

        cuota_inicio = None
        if monto_recibido <= 0 and cuota_id:
            cuota_inicio = get_object_or_404(Cuota, id=cuota_id)
            monto_recibido = cuota_inicio.saldo_cuota

        if monto_recibido <= 0:
            messages.error(request, "Debe seleccionar una cuota o ingresar un monto.")
            return redirect(request.path)

        # 2. DETERMINAR QUÉ CUOTAS PROCESAR
        if cuota_id:
            if not cuota_inicio:
                cuota_inicio = get_object_or_404(Cuota, id=cuota_id)
            
            cuotas_a_procesar = targeta.cuotas.filter(
                estado='PENDIENTE', 
                numero__gte=cuota_inicio.numero
            ).order_by('numero')
        else:
            cuotas_a_procesar = cuotas_pendientes

        # 3. PROCESAMIENTO EN CASCADA
        monto_original = monto_recibido
        ruta = targeta.ruta
        
        with transaction.atomic(): # Asegura que todo se guarde o nada
            for cuota in cuotas_a_procesar:
                if monto_recibido <= 0: break
                
                saldo_actual = cuota.saldo_cuota if cuota.saldo_cuota is not None else Decimal('0.00')
                if saldo_actual <= 0: continue
                
                pago_a_cuota = min(saldo_actual, monto_recibido)
                
                cuota.saldo_cuota = saldo_actual - pago_a_cuota
                if cuota.saldo_cuota <= 0:
                    cuota.estado = 'PAGADA'
                    cuota.saldo_cuota = 0
                    cuota.fecha_pago = now()
                cuota.save()

                Abono.objects.create(
                    targeta=targeta,
                    cuota=cuota,
                    monto=pago_a_cuota,
                    registrado_por=request.user
                )
                monto_recibido -= pago_a_cuota

            # 4. ACTUALIZACIÓN DE CAJA
            ruta.base += monto_original
            ruta.save(update_fields=['base'])

            MovimientoRuta.objects.create(
                ruta=ruta, tipo='INGRESO', monto=monto_original,
                descripcion=f"Abono - Cliente: {targeta.nombre_cliente}"
            )

            # --- LÓGICA DE CIERRE AUTOMÁTICO (SOLUCIÓN AL PROBLEMA) ---
            # Si después del abono el saldo es 0 o menor, marcamos como PAGADA
            if targeta.saldo_restante <= 0:
                targeta.estado = 'PAGADA'
                targeta.save(update_fields=['estado'])
            else:
                targeta.actualizar_estado() 

        messages.success(request, f"Se registró un pago de ${monto_original} correctamente.")

        # Redirección por Rol
        user_rol = request.user.perfil.rol if hasattr(request.user, 'perfil') else 'TRABAJADOR'
        if user_rol == 'SUPERVISOR' or request.user.is_staff:
            return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")
        return redirect(f"/dashboard/trabajador/?ruta={ruta.id}")

    return render(request, "app/crear_abono.html", {
        "targeta": targeta,
        "cuotas": cuotas_pendientes,
    })

@login_required
def historial_abonos(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id)
    rol = request.user.perfil.rol

    # 🔒 permisos
    if rol == 'SUPERVISOR' and targeta.ruta.supervisor != request.user:
        messages.error(request, "No autorizado")
        return redirect('dashboard')

    if rol == 'TRABAJADOR' and request.user not in targeta.ruta.trabajadores.all():
        messages.error(request, "No autorizado")
        return redirect('dashboard')

    abonos = Abono.objects.filter(targeta=targeta).order_by('-fecha')

    total_abonado = abonos.aggregate(
        total=Sum('monto')
    )['total'] or Decimal('0.00')

    return render(request, "app/historial_abonos.html", {
        "targeta": targeta,
        "abonos": abonos,
        "total_abonado": total_abonado
    })



@login_required
def retiro_justificado(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if request.user != ruta.supervisor:
        messages.error(request, "No autorizado")
        return redirect('dashboard')

    if request.method == "POST":
        monto = Decimal(request.POST.get("monto"))

        if monto <= 0:
            messages.error(request, "Monto inválido")
            return redirect(request.path)

        # RESTA DIRECTA A LA BASE
        ruta.base -= monto
        ruta.save(update_fields=['base'])

        messages.success(request, "Retiro registrado correctamente")
        return redirect('resumen_caja', ruta_id=ruta.id)

    return render(request, 'app/retiro_justificado.html', {
        'ruta': ruta
    })



from django.db import models # Asegúrate de tener esta importación al inicio del archivo

@login_required
def historial_cajas(request, ruta_id):
    import calendar
    import datetime

    ruta = get_object_or_404(Ruta, id=ruta_id)

    # ── Mes seleccionado ──────────────────────────────────────
    mes_param = request.GET.get('mes')
    hoy = localdate()

    try:
        if mes_param:
            anio, mes = int(mes_param.split('-')[0]), int(mes_param.split('-')[1])
        else:
            anio, mes = hoy.year, hoy.month
    except Exception:
        anio, mes = hoy.year, hoy.month

    primer_dia = datetime.date(anio, mes, 1)
    ultimo_dia = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
    mes_param_str = f'{anio}-{str(mes).zfill(2)}'

    # ── Abonos del mes agrupados por día ─────────────────────
    abonos_mes = (
        Abono.objects
        .filter(targeta__ruta=ruta, fecha__date__gte=primer_dia, fecha__date__lte=ultimo_dia)
        .values('fecha__date')
        .annotate(total=Sum('monto'))
    )
    abonos_por_dia = {a['fecha__date']: a['total'] for a in abonos_mes}

    # ── Egresos del mes agrupados por día ────────────────────
    egresos_mes = (
        MovimientoRuta.objects
        .filter(ruta=ruta, tipo='EGRESO', fecha__date__gte=primer_dia, fecha__date__lte=ultimo_dia)
        .values('fecha__date')
        .annotate(total=Sum('monto'))
    )
    egresos_por_dia = {e['fecha__date']: e['total'] for e in egresos_mes}

    # ── Días con actividad ────────────────────────────────────
    dias_con_actividad = sorted(
        set(list(abonos_por_dia.keys()) + list(egresos_por_dia.keys())),
        reverse=True
    )

    dias = []
    for dia in dias_con_actividad:
        ingresos_dia = abonos_por_dia.get(dia, Decimal('0.00'))
        egresos_dia  = egresos_por_dia.get(dia, Decimal('0.00'))

        movimientos = []

        abonos_detalle = (
            Abono.objects
            .filter(targeta__ruta=ruta, fecha__date=dia)
            .select_related('targeta')
            .order_by('fecha')
        )
        for a in abonos_detalle:
            movimientos.append({
                'tipo': 'INGRESO',
                'descripcion': f'Abono — {a.targeta.nombre_cliente}',
                'monto': a.monto,
                'hora': a.fecha,
            })

        egresos_detalle = (
            MovimientoRuta.objects
            .filter(ruta=ruta, tipo='EGRESO', fecha__date=dia)
            .order_by('fecha')
        )
        for e in egresos_detalle:
            movimientos.append({
                'tipo': 'EGRESO',
                'descripcion': e.descripcion,
                'monto': e.monto,
                'hora': e.fecha,
            })

        movimientos.sort(key=lambda x: x['hora'])

        dias.append({
            'fecha': dia,
            'ingresos': ingresos_dia,
            'egresos': egresos_dia,
            'neto': ingresos_dia - egresos_dia,
            'movimientos': movimientos,
        })

    # ── Resumen mensual ───────────────────────────────────────
    total_ingresos_mes = sum(d['ingresos'] for d in dias)
    total_egresos_mes  = sum(d['egresos']  for d in dias)
    neto_mes           = total_ingresos_mes - total_egresos_mes

    # ── Meses disponibles para el selector ───────────────────
    primer_abono = (
        Abono.objects
        .filter(targeta__ruta=ruta)
        .order_by('fecha')
        .first()
    )
    meses_disponibles = []
    if primer_abono:
        cur = primer_abono.fecha.date().replace(day=1)
        fin = hoy.replace(day=1)
        while cur <= fin:
            meses_disponibles.append(cur)
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
        meses_disponibles.reverse()

    return render(request, 'app/historial_cajas.html', {
        'ruta': ruta,
        'dias': dias,
        'mes_actual': primer_dia,
        'total_ingresos_mes': total_ingresos_mes,
        'total_egresos_mes': total_egresos_mes,
        'neto_mes': neto_mes,
        'meses_disponibles': meses_disponibles,
        'mes_param': mes_param_str,
    })

# =====================================================
# 🔒 CIERRE AUTOMÁTICO DE CAJAS ANTRIORES
# =====================================================
def cerrar_cajas_anteriores(ruta):
    hoy = localdate()

    cajas_abiertas = CajaRuta.objects.filter(
        ruta=ruta,
        cerrada=False
    ).exclude(fecha=hoy)

    for caja in cajas_abiertas:
        ingresos = Abono.objects.filter(
            targeta__ruta=ruta,
            fecha__date=caja.fecha
        ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

        egresos = MovimientoRuta.objects.filter(
            ruta=ruta,
            tipo="EGRESO",
            fecha__date=caja.fecha
        ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

        caja.ingresos = ingresos
        caja.egresos = egresos
        caja.saldo_final = caja.saldo_inicial + ingresos - egresos
        caja.cerrada = True
        caja.save()


# =====================================================
# 📊 MOVIMIENTOS DE RUTA (CAJA DEL DÍA)
# =====================================================
from datetime import timedelta # Asegúrate de tener esta importación arriba

@login_required
def movimientos_ruta(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if request.user != ruta.supervisor:
        messages.error(request, "No autorizado")
        return redirect("dashboard")

    hoy = localdate()

    # ===============================
    # 🔒 CERRAR CAJAS ANTERIORES
    # ===============================
    # Llamamos a la lógica de cierre para que si hay días pendientes, se procesen.
    try:
        from django.core.management import call_command
        call_command('cerrar_cajas') 
    except Exception as e:
        print(f"Error en cierre automático: {e}")

    # Refrescamos el objeto ruta por si el comando cambió la base
    ruta.refresh_from_db()

    # ===============================
    # 📦 CAJA DEL DÍA
    # ===============================
    # Buscamos si ya existe la caja de hoy. 
    # Si no existe, se crea usando la base actual de la ruta.
    caja, created = CajaRuta.objects.get_or_create(
        ruta=ruta,
        fecha=hoy,
        defaults={"saldo_inicial": ruta.base}
    )

    # ===============================
    # 📥 INGRESOS (Abonos de hoy)
    # ===============================
    abonos = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__gte=hoy,
        fecha__lt=hoy + timedelta(days=1)
    )

    ingresos_hoy = abonos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # ===============================
    # 📤 EGRESOS (Gastos/Retiros de hoy)
    # ===============================
    egresos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo="EGRESO",
        fecha__gte=hoy,
        fecha__lt=hoy + timedelta(days=1)
    )

    egresos_hoy = egresos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # ===============================
    # 💾 ACTUALIZAR CAJA
    # ===============================
    caja.ingresos = ingresos_hoy
    caja.egresos = egresos_hoy
    caja.save()

    # El saldo actual es lo que había al empezar + lo que entró - lo que salió
    saldo_hoy = caja.saldo_inicial + ingresos_hoy - egresos_hoy

    # ===============================
    # 🧾 LISTADO DE MOVIMIENTOS
    # ===============================
    movimientos = []

    for a in abonos:
        movimientos.append({
            "fecha": a.fecha,
            "tipo": "INGRESO",
            "monto": a.monto,
            "descripcion": f"Abono - {a.targeta.nombre_cliente}"
        })

    for e in egresos:
        movimientos.append({
            "fecha": e.fecha,
            "tipo": "EGRESO",
            "monto": e.monto,
            "descripcion": e.descripcion
        })

    # Ordenar por hora (más reciente primero)
    movimientos.sort(key=lambda x: x["fecha"], reverse=True)

    return render(request, "app/movimientos_ruta.html", {
        "ruta": ruta,
        "caja": caja,
        "movimientos": movimientos,
        "ingresos_hoy": ingresos_hoy,
        "egresos_hoy": egresos_hoy,
        "saldo_hoy": saldo_hoy,
    })

@login_required
def reporte_diario(request, ruta_id, fecha):
    ruta = get_object_or_404(Ruta, id=ruta_id)
    
    if request.user != ruta.supervisor:
        return redirect("dashboard")

    # 1. Convertir fecha usando el módulo explícito
    try:
        fecha_reporte = datetime.datetime.strptime(fecha, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return redirect("dashboard_supervisor")

    # 2. Rangos de tiempo (Corregido para evitar el 500)
    inicio_dia = make_aware(datetime.datetime.combine(fecha_reporte, datetime.time.min))
    fin_dia = make_aware(datetime.datetime.combine(fecha_reporte, datetime.time.max))
    hoy = localdate()

    # 3. Obtener o crear Caja
    caja, created = CajaRuta.objects.get_or_create(
        ruta=ruta, 
        fecha=fecha_reporte,
        defaults={'saldo_inicial': ruta.base, 'cerrada': False}
    )

    # 4. Consultar Datos
    abonos = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__range=(inicio_dia, fin_dia)
    ).order_by("fecha")

    egresos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo="EGRESO",
        fecha__range=(inicio_dia, fin_dia)
    ).order_by("fecha")

    # 5. Cálculos con Decimal
    total_ingresos = abonos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")
    total_egresos = egresos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # 6. Actualización de Caja
    caja.ingresos = total_ingresos
    caja.egresos = total_egresos
    caja.saldo_final = caja.saldo_inicial + total_ingresos - total_egresos
    
    if fecha_reporte < hoy:
        caja.cerrada = True
    caja.save()

    return render(request, "app/reporte_diario.html", {
        "ruta": ruta,
        "fecha": fecha_reporte,
        "caja": caja,
        "abonos": abonos,
        "egresos": egresos,
        "total_ingresos": total_ingresos,
        "total_egresos": total_egresos,
        "saldo_inicial": caja.saldo_inicial,
        "saldo_final": caja.saldo_final,
    })

def crear_cuotas(targeta):
    """
    Genera cuotas con fecha de vencimiento. 
    1. Si es tarde (8 PM+), inicia un día después.
    2. Si un vencimiento cae DOMINGO, se pasa al LUNES.
    """
    monto_total = targeta.monto_total
    plazo = targeta.plazo_dias
    monto_cuota = (monto_total / Decimal(plazo)).quantize(Decimal('0.01'))
    
    HORA_CORTE = 20  # 8:00 PM
    ahora = timezone.localtime(timezone.now())
    # Definimos desde cuándo empezamos a contar los días del plazo
    dia_referencia = localdate()

    if ahora.hour >= HORA_CORTE:
        dia_referencia = dia_referencia + datetime.timedelta(days=1)

    # Creamos las cuotas una por una
    for i in range(1, plazo + 1):
        # Calculamos la fecha tentativa (sumando i días al día de referencia)
        vencimiento = dia_referencia + datetime.timedelta(days=i)
        
        # --- LÓGICA EXCLUIR DOMINGOS ---
        if vencimiento.weekday() == 6: 
            vencimiento = vencimiento + datetime.timedelta(days=1)
        # -------------------------------
        
        Cuota.objects.create(
            targeta=targeta,
            numero=i,
            monto=monto_cuota,
            saldo_cuota=monto_cuota,  # <--- IMPORTANTE: Se añade el saldo inicial aquí
            fecha_vencimiento=vencimiento,
            estado='PENDIENTE'
        )
    
    targeta.actualizar_estado()

from decimal import Decimal # Importante para manejar dinero con exactitud
from django.db import transaction # Para asegurar que si falla algo, no se reste dinero a medias



from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal
from datetime import date
# Asegúrate de importar tus modelos
# from .models import Ruta, MovimientoRuta 

@login_required
def registrar_gasto(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)
    hoy = date.today()

    # --- LÓGICA PARA EL MODAL (NUEVO) ---
    # Obtenemos los movimientos de tipo EGRESO para esta ruta en el mes actual
    gastos_mes_qs = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        fecha__month=hoy.month,
        fecha__year=hoy.year
    ).order_by('-fecha')

    # Sumamos el total de esos gastos
    total_gastos_mes = gastos_mes_qs.aggregate(Sum('monto'))['monto__sum'] or 0

    # --- PROCESAMIENTO DEL FORMULARIO ---
    if request.method == 'POST':
        monto_str = request.POST.get('monto')
        descripcion = request.POST.get('descripcion')
        
        try:
            if monto_str:
                monto = Decimal(monto_str)
                
                if monto <= 0:
                    messages.error(request, "El monto debe ser mayor a cero.")
                
                # Verificamos si la base aguanta el gasto
                elif ruta.base < monto:
                    messages.error(request, f"⚠️ Fondos insuficientes. La base actual es ${ruta.base}")
                
                else:
                    # Transacción atómica para seguridad de datos
                    with transaction.atomic():
                        # 1. RESTAMOS DE LA BASE
                        ruta.base -= monto
                        ruta.save()

                        # 2. CREAMOS EL MOVIMIENTO
                        MovimientoRuta.objects.create(
                            ruta=ruta,
                            tipo='EGRESO',
                            monto=monto,
                            descripcion=f"GASTO: {descripcion}"
                        )

                    messages.success(request, f"✅ Gasto de ${monto} descontado de la base.")
                    return redirect(f'/dashboard/supervisor/?ruta={ruta.id}')
            else:
                messages.error(request, "El monto es obligatorio.")
                
        except Exception as e:
            messages.error(request, f"Error al procesar el gasto: {e}")
            
    # Enviamos los datos al template (incluyendo los del modal)
    context = {
        'ruta': ruta,
        'gastos_recientes': gastos_mes_qs,  # Para la tablita del modal
        'total_gastos_mes': total_gastos_mes # Para el encabezado del modal
    }
    
    return render(request, 'app/registrar_gasto.html', context)













@login_required
def eliminar_abono(request, abono_id):
    abono = get_object_or_404(Abono, id=abono_id)
    targeta = abono.targeta
    ruta = targeta.ruta

    # Seguridad: Solo Supervisor de esta ruta o Staff
    if request.user != ruta.supervisor and not request.user.is_staff:
        messages.error(request, "No tienes permiso para eliminar abonos.")
        return redirect('historial_abonos', targeta_id=targeta.id)

    with transaction.atomic():
        # 1. Devolver el saldo a la cuota
        if abono.cuota:
            cuota = abono.cuota
            cuota.saldo_cuota += abono.monto
            cuota.estado = 'PENDIENTE'
            cuota.fecha_pago = None
            cuota.save()

        # 2. Restar de la base de la ruta
        ruta.base -= abono.monto
        ruta.save()

        # 3. Crear un movimiento de salida para dejar rastro (Auditoría)
        MovimientoRuta.objects.create(
            ruta=ruta,
            tipo='EGRESO',
            monto=abono.monto,
            descripcion=f"ANULACIÓN ABONO - Cliente: {targeta.nombre_cliente} (Abono ID: {abono.id})"
        )

        # 4. Eliminar el abono
        abono.delete()
        
        # 5. Actualizar estado de la tarjeta (por si vuelve a mora)
        targeta.actualizar_estado()

    messages.success(request, f"Abono eliminado. Se han devuelto ${abono.monto} a la deuda.")
    return redirect('historial_abonos', targeta_id=targeta.id)




@login_required
@supervisor_required
def renovar_targeta(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    ruta = targeta.ruta

    if request.method == "POST":
        monto = Decimal(request.POST.get("monto_base"))
        tasa = int(request.POST.get("tasa_interes"))
        plazo = int(request.POST.get("plazo_dias"))

        if monto > ruta.base:
            messages.error(request, "Base insuficiente en la ruta.")
            return redirect(request.path)

        try:
            with transaction.atomic():
                # 1. Limpiar historial de cuotas y abonos viejos (Para que no se mezclen)
                targeta.cuotas.all().delete()
                targeta.abonos.all().delete()

                # 2. Restaurar valores de la tarjeta
                targeta.monto_base = monto
                targeta.tasa_interes = tasa
                targeta.plazo_dias = plazo
                targeta.estado = 'AL_DIA' # Vuelve a estar activa
                targeta.save()

                # 3. Generar nuevas cuotas
                crear_cuotas(targeta)

                # 4. Descontar de la base y registrar movimiento
                ruta.base -= monto
                ruta.save()

                MovimientoRuta.objects.create(
                    ruta=ruta,
                    tipo='EGRESO',
                    monto=monto,
                    descripcion=f"RENOVACIÓN (Restauración): {targeta.nombre_cliente}"
                )

            messages.success(request, f"Crédito restaurado para {targeta.nombre_cliente}")
            return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

        except Exception as e:
            messages.error(request, f"Error: {e}")

    return render(request, "app/renovar_targeta.html", {"targeta": targeta})


@login_required
@supervisor_required
def clientes_finalizados(request):
    rutas = Ruta.objects.filter(supervisor=request.user)
    ruta_id = request.GET.get("ruta")
    
    # Buscamos tarjetas del supervisor
    query = Targeta.objects.filter(ruta__supervisor=request.user)
    
    if ruta_id:
        query = query.filter(ruta_id=ruta_id)

    # FILTRO CLAVE: Traemos las que ya están marcadas PAGADA 
    # O las que detectamos que ya no deben nada (saldo_restante == 0)
    targetas = [t for t in query if t.estado == 'PAGADA' or t.saldo_restante <= 0]

    return render(request, "app/clientes_finalizados.html", {
        "targetas": targetas,
        "rutas": rutas,
        "ruta_sel": rutas.filter(id=ruta_id).first() if ruta_id else None
    })





def historial_cierres(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)
    historial = ReporteDiario.objects.filter(ruta=ruta).order_by('-fecha')

    # Inyectamos los movimientos de cada día dentro de cada registro del historial
    for registro in historial:
        registro.movimientos_del_dia = MovimientoRuta.objects.filter(
            ruta=ruta,
            fecha__date=registro.fecha # Filtra movimientos de ese mismo día
        ).order_by('fecha')

    return render(request, 'app/historial_cierres.html', {
        'ruta': ruta,
        'historial': historial
    })


def mapa_clientes(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)
    # Solo traemos las tarjetas que tengan ubicación guardada
    clientes = Targeta.objects.filter(ruta=ruta).exclude(latitud=None).exclude(longitud=None)
    
    return render(request, 'app/mapa_clientes.html', {
        'ruta': ruta,
        'clientes': clientes
    })


def guardar_gps_cliente(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id)
    
    if request.method == 'POST':
        lat = request.POST.get('latitud')
        lng = request.POST.get('longitud')
        
        # Guardamos las coordenadas numéricas
        targeta.latitud = lat
        targeta.longitud = lng
        
        # Reemplazamos la dirección de texto por el link real
        targeta.direccion_casa = f"https://www.google.com/maps?q={lat},{lng}"
        targeta.save()
        
        return JsonResponse({'status': 'success'})
    

    from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from .models import Targeta

def validar_gps_cliente(request, pk):
    # Buscamos la tarjeta por su ID (pk)
    targeta = get_object_or_404(Targeta, pk=pk)
    
    if request.method == 'POST':
        lat = request.POST.get('latitud')
        lng = request.POST.get('longitud')
        
        if lat and lng:
            # Guardamos las coordenadas en el modelo
            targeta.latitud = float(lat)
            targeta.longitud = float(lng)
            
            # También actualizamos el campo de dirección con el link de Google Maps
            targeta.direccion_casa = f"https://www.google.com/maps?q={lat},{lng}"
            targeta.save()
            
            return JsonResponse({'status': 'ok', 'message': 'Ubicación guardada correctamente'})
            
    # Si es un GET (cuando el cliente abre el link), mostramos la página de validación
    return render(request, 'app/validar_gps.html', {'targeta': targeta})