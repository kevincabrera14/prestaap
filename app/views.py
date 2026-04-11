#views 

# ===============================================================================================================================================================
# import
# ===============================================================================================================================================================


from django.utils.timezone import localtime, make_aware, get_current_timezone, localdate, now
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .permissions import supervisor_required
from .models import Ruta, Targeta, Abono, MovimientoRuta, CajaRuta, Cuota
from django.contrib import messages
from django.db.models import Sum, Q, F, Count
from django.db import transaction
from decimal import Decimal
import datetime
from django.http import HttpResponse
from django.contrib.auth.decorators import user_passes_test
from django.urls import reverse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from datetime import date
from datetime import timedelta 
from decimal import Decimal 
from django.db import transaction 
from django.http import JsonResponse
from django.utils import timezone

# ===============================================================================================================================================================
# AUTH
# ===============================================================================================================================================================


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


# ===================================================================================================================================================================
# DASHBOARD CENTRAL
# ========================================================================================================================================================================


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


# ================================================================================================================================================
# ADMIN
# ================================================================================================================================================

@login_required
def dashboard_admin(request):
    rutas = Ruta.objects.select_related('supervisor').prefetch_related('trabajadores')
    return render(request, 'app/admin.html', {'rutas': rutas})

# ================================================================================================================================================
# SUPERVISOR
# ================================================================================================================================================


@login_required
@supervisor_required
def dashboard_supervisor(request):
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
        ruta_sel = get_object_or_404(Ruta, id=ruta_id, supervisor=request.user)

        query = Targeta.objects.filter(ruta=ruta_sel).exclude(estado='PAGADA')

        if q:
            query = query.filter(nombre_cliente__icontains=q)

        targetas_raw = [t for t in query if t.saldo_restante > 0]

        # ── Preparar rangos de "hoy" para detectar abono_hoy ─────────────
        hoy_fecha = localdate()
        hoy_inicio_aware = make_aware(
            datetime.datetime.combine(hoy_fecha, datetime.time.min)
        )
        hoy_fin_aware = make_aware(
            datetime.datetime.combine(hoy_fecha, datetime.time.max)
        )

        targetas = []
        for t in targetas_raw:
            t.cuotas_pagadas = t.cuotas.filter(estado='PAGADA').count()
            t.total_cuotas   = t.cuotas.count()

            # ── ¿Pagó hoy? ───────────────────────────────────────────────
            t.abono_hoy = t.abonos.filter(
                fecha__gte=hoy_inicio_aware,
                fecha__lte=hoy_fin_aware,
            ).exists()

            # ── Días desde el último abono ────────────────────────────────
            ultimo_abono = t.abonos.order_by('-fecha').first()
            if ultimo_abono:
                t.dias_sin_abono = (hoy_fecha - ultimo_abono.fecha.date()).days
            else:
                t.dias_sin_abono = (hoy_fecha - t.fecha_creacion).days

            # ── ¿Cobro atrasado según frecuencia? ─────────────────────────
            if t.frecuencia_cobro == 'DIARIO':
                t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 1)
            elif t.frecuencia_cobro == 'SEMANAL':
                t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 7)
            elif t.frecuencia_cobro == 'QUINCENAL':
                t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 15)
            elif t.frecuencia_cobro == 'MENSUAL':
                t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 30)
            else:
                t.cobro_atrasado = False

            targetas.append(t)

        # ── Resumen financiero ────────────────────────────────────────────
        resumen["total_clientes"] = len(targetas)
        resumen["en_mora"]        = len([t for t in targetas if t.estado == "MORA"])
        resumen["base"]           = ruta_sel.base
        resumen["dinero_en_ruta"] = sum(t.saldo_restante for t in targetas)

    context = {
        "rutas":     rutas,
        "ruta_sel":  ruta_sel,
        "targetas":  targetas,
        "resumen":   resumen,
    }

    return render(request, "app/supervisor.html", context)


# ================================================================================================================================================
# TRABAJADOR
# ================================================================================================================================================

@login_required
def dashboard_trabajador(request):
    rutas = Ruta.objects.filter(trabajadores=request.user)
    targetas_qs = Targeta.objects.filter(ruta__in=rutas).exclude(estado='PAGADA')

    q       = request.GET.get("q")
    estado  = request.GET.get("estado")
    ruta_id = request.GET.get("ruta")

    if q:
        targetas_qs = targetas_qs.filter(nombre_cliente__icontains=q)
    if estado:
        targetas_qs = targetas_qs.filter(estado=estado)
    if ruta_id:
        targetas_qs = targetas_qs.filter(ruta_id=ruta_id)

    targetas_qs = targetas_qs.prefetch_related('cuotas', 'abonos')

    # Rangos de hoy para detectar abono_hoy
    hoy_fecha        = localdate()
    hoy_inicio_aware = make_aware(datetime.datetime.combine(hoy_fecha, datetime.time.min))
    hoy_fin_aware    = make_aware(datetime.datetime.combine(hoy_fecha, datetime.time.max))

    targetas = []
    for t in targetas_qs:
        if t.saldo_restante <= 0:
            continue

        todas_las_cuotas = t.cuotas.all()
        t.cuotas_pagadas = sum(1 for c in todas_las_cuotas if c.estado == 'PAGADA')
        t.total_cuotas   = len(todas_las_cuotas)

        # ¿Pagó hoy?
        t.abono_hoy = t.abonos.filter(
            fecha__gte=hoy_inicio_aware,
            fecha__lte=hoy_fin_aware,
        ).exists()

        # Dias desde el ultimo abono
        ultimo_abono = t.abonos.order_by('-fecha').first()
        if ultimo_abono:
            t.dias_sin_abono = (hoy_fecha - ultimo_abono.fecha.date()).days
        else:
            t.dias_sin_abono = (hoy_fecha - t.fecha_creacion).days

        # ¿Cobro atrasado segun frecuencia?
        if t.frecuencia_cobro == 'DIARIO':
            t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 1)
        elif t.frecuencia_cobro == 'SEMANAL':
            t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 7)
        elif t.frecuencia_cobro == 'QUINCENAL':
            t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 15)
        elif t.frecuencia_cobro == 'MENSUAL':
            t.cobro_atrasado = (not t.abono_hoy) and (t.dias_sin_abono > 30)
        else:
            t.cobro_atrasado = False

        targetas.append(t)

    resumen = {
        "total_clientes": len(targetas),
        "en_mora":        sum(1 for t in targetas if t.estado == "MORA"),
        "total_saldo":    sum(t.saldo_restante for t in targetas),
    }

    return render(request, "app/trabajador.html", {
        "rutas":    rutas,
        "targetas": targetas,
        "resumen":  resumen,
        "ruta_sel": Ruta.objects.filter(id=ruta_id).first() if ruta_id else None,
    })


# ================================================================================================================================================
# RUTA
# ================================================================================================================================================


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


# ================================================================================================================================================
# TARGETAS
# ================================================================================================================================================


@login_required
@supervisor_required
def crear_targeta(request):
    rutas = Ruta.objects.filter(supervisor=request.user)

    if request.method == "POST":
        ruta_id    = request.POST.get("ruta")
        monto_base = request.POST.get("monto_base")
        tasa_interes = request.POST.get("tasa_interes")
        plazo_dias   = request.POST.get("plazo_dias")

        if not all([ruta_id, monto_base, tasa_interes, plazo_dias]):
            messages.error(request, "Todos los campos obligatorios deben ser completados")
            return redirect(request.path)

        ruta = get_object_or_404(Ruta, id=ruta_id)

        try:
            monto = Decimal(monto_base)
            tasa  = int(tasa_interes)
            plazo = int(plazo_dias)
        except (ValueError, TypeError):
            messages.error(request, "Los valores numéricos no son válidos")
            return redirect(request.path)

        if monto > ruta.base:
            messages.error(request, f"Base insuficiente en la ruta. Saldo actual: ${ruta.base}")
            return redirect(f"{request.path}?ruta={ruta_id}")

        ruta.base -= monto
        ruta.save(update_fields=['base'])

        # ── Frecuencia de cobro ───────────────────────────────────────────
        frecuencia = request.POST.get("frecuencia_cobro", "DIARIO")
        if frecuencia not in ('DIARIO', 'SEMANAL', 'QUINCENAL', 'MENSUAL'):
            frecuencia = 'DIARIO'

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
            frecuencia_cobro=frecuencia,
            creada_por=request.user
        )

        crear_cuotas(targeta)

        MovimientoRuta.objects.create(
            ruta=ruta,
            tipo='EGRESO',
            monto=monto,
            descripcion=f'Préstamo otorgado a {targeta.nombre_cliente}'
        )

        messages.success(request, "Tarjeta creada correctamente")
        return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

    return render(request, 'app/crear_targeta.html', {'rutas': rutas})

@login_required
@supervisor_required
def editar_targeta(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    rutas = Ruta.objects.filter(supervisor=request.user)

    if request.method == "POST":
        try:
            nueva_ruta_id = request.POST.get("ruta")
            if nueva_ruta_id:
                targeta.ruta_id = int(nueva_ruta_id)

            campos_texto = [
                "tipo_identificacion", "numero_identificacion", "nombre_cliente",
                "telefono", "direccion_casa", "direccion_negocio", "observaciones"
            ]
            for campo in campos_texto:
                setattr(targeta, campo, request.POST.get(campo))

            targeta.tasa_interes = int(request.POST.get("tasa_interes", targeta.tasa_interes))
            targeta.plazo_dias   = int(request.POST.get("plazo_dias",   targeta.plazo_dias))

            # ── Frecuencia de cobro ───────────────────────────────────────
            frecuencia = request.POST.get("frecuencia_cobro")
            if frecuencia in ('DIARIO', 'SEMANAL', 'QUINCENAL', 'MENSUAL'):
                targeta.frecuencia_cobro = frecuencia

            monto_base_post = request.POST.get("monto_base")
            if monto_base_post:
                targeta.monto_base = Decimal(monto_base_post)
                interes_decimal = Decimal(targeta.tasa_interes) / 100
                targeta.monto_total = targeta.monto_base + (targeta.monto_base * interes_decimal)

            targeta.save()
            messages.success(request, f"¡Tarjeta de {targeta.nombre_cliente} actualizada correctamente!")
            return redirect(f"/dashboard/supervisor/?ruta={targeta.ruta.id}")

        except Exception as e:
            messages.error(request, f"Error al actualizar: {str(e)}")
            return redirect(request.path)

    return render(request, "app/editar_targeta.html", {
        "targeta": targeta,
        "rutas":   rutas
    })

@login_required
@supervisor_required
def eliminar_targeta(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    ruta           = targeta.ruta
    saldo_perdido  = targeta.saldo_restante
    nombre_cliente = targeta.nombre_cliente

    try:
        with transaction.atomic():
            if saldo_perdido > 0:
                MovimientoRuta.objects.create(
                    ruta=ruta,
                    tipo='EGRESO',
                    monto=saldo_perdido,
                    descripcion=f"ELIMINACIÓN TARJETA (Pérdida) - Cliente: {nombre_cliente}"
                )
            targeta.delete()

        messages.success(request, f"Tarjeta de {nombre_cliente} eliminada. Se registró un egreso de ${saldo_perdido} por saldo pendiente.")
    except Exception as e:
        messages.error(request, f"Error al eliminar la tarjeta: {str(e)}")

    return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

@login_required
@supervisor_required
def renovar_targeta(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    ruta = targeta.ruta

    if request.method == "POST":
        monto = Decimal(request.POST.get("monto_base"))
        tasa  = int(request.POST.get("tasa_interes"))
        plazo = int(request.POST.get("plazo_dias"))

        if monto > ruta.base:
            messages.error(request, "Base insuficiente en la ruta.")
            return redirect(request.path)

        try:
            with transaction.atomic():
                targeta.cuotas.all().delete()
                targeta.abonos.all().delete()

                targeta.monto_base   = monto
                targeta.tasa_interes = tasa
                targeta.plazo_dias   = plazo
                targeta.estado       = 'AL_DIA'
                targeta.save()

                crear_cuotas(targeta)

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
    rutas   = Ruta.objects.filter(supervisor=request.user)
    ruta_id = request.GET.get("ruta")

    query = Targeta.objects.filter(ruta__supervisor=request.user)
    if ruta_id:
        query = query.filter(ruta_id=ruta_id)

    targetas = [t for t in query if t.estado == 'PAGADA' or t.saldo_restante <= 0]

    return render(request, "app/clientes_finalizados.html", {
        "targetas": targetas,
        "rutas":    rutas,
        "ruta_sel": rutas.filter(id=ruta_id).first() if ruta_id else None
    })


# ================================================================================================================================================
# ABONOS
# ================================================================================================================================================


@login_required
@supervisor_required
def lista_abonos(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    abonos  = targeta.abonos.all().order_by('-fecha')

    return render(request, 'app/lista_abonos.html', {
        'targeta': targeta,
        'abonos':  abonos
    })

@login_required
def crear_abono(request, targeta_id=None):
    if not targeta_id:
        targeta_id = request.POST.get("targeta") or request.GET.get("targeta")

    targeta           = None
    cuotas_pendientes = []
    if targeta_id:
        targeta           = get_object_or_404(Targeta, id=targeta_id)
        cuotas_pendientes = targeta.cuotas.filter(estado='PENDIENTE').order_by('numero')

    if request.method == "POST" and targeta:
        cuota_id    = request.POST.get("cuota")
        monto_input = request.POST.get("monto_abono")

        try:
            monto_recibido = Decimal(monto_input) if monto_input and Decimal(monto_input) > 0 else Decimal(0)
        except (ValueError, TypeError, Decimal.InvalidOperation):
            monto_recibido = Decimal(0)

        cuota_inicio = None
        if monto_recibido <= 0 and cuota_id:
            cuota_inicio   = get_object_or_404(Cuota, id=cuota_id)
            monto_recibido = cuota_inicio.saldo_cuota

        if monto_recibido <= 0:
            messages.error(request, "Debe seleccionar una cuota o ingresar un monto.")
            return redirect(request.path)

        if cuota_id:
            if not cuota_inicio:
                cuota_inicio = get_object_or_404(Cuota, id=cuota_id)
            cuotas_a_procesar = targeta.cuotas.filter(
                estado='PENDIENTE',
                numero__gte=cuota_inicio.numero
            ).order_by('numero')
        else:
            cuotas_a_procesar = cuotas_pendientes

        monto_original = monto_recibido
        ruta = targeta.ruta

        with transaction.atomic():
            for cuota in cuotas_a_procesar:
                if monto_recibido <= 0:
                    break

                saldo_actual = cuota.saldo_cuota if cuota.saldo_cuota is not None else Decimal('0.00')
                if saldo_actual <= 0:
                    continue

                pago_a_cuota  = min(saldo_actual, monto_recibido)
                cuota.saldo_cuota = saldo_actual - pago_a_cuota
                if cuota.saldo_cuota <= 0:
                    cuota.estado     = 'PAGADA'
                    cuota.saldo_cuota = 0
                    cuota.fecha_pago  = now()
                cuota.save()

                Abono.objects.create(
                    targeta=targeta,
                    cuota=cuota,
                    monto=pago_a_cuota,
                    registrado_por=request.user
                )
                monto_recibido -= pago_a_cuota

            ruta.base += monto_original
            ruta.save(update_fields=['base'])

            MovimientoRuta.objects.create(
                ruta=ruta, tipo='INGRESO', monto=monto_original,
                descripcion=f"Abono - Cliente: {targeta.nombre_cliente}"
            )

            if targeta.saldo_restante <= 0:
                targeta.estado = 'PAGADA'
                targeta.save(update_fields=['estado'])
            else:
                targeta.actualizar_estado()

        messages.success(request, f"Se registró un pago de ${monto_original} correctamente.")

        user_rol = request.user.perfil.rol if hasattr(request.user, 'perfil') else 'TRABAJADOR'
        if user_rol == 'SUPERVISOR' or request.user.is_staff:
            return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")
        return redirect(f"/dashboard/trabajador/?ruta={ruta.id}")

    return render(request, "app/crear_abono.html", {
        "targeta": targeta,
        "cuotas":  cuotas_pendientes,
    })


def crear_cuotas(targeta):
    """
    Genera cuotas con fecha de vencimiento.
    1. Si es tarde (8 PM+), inicia un día después.
    2. Si un vencimiento cae DOMINGO, se pasa al LUNES.
    """
    monto_total  = targeta.monto_total
    plazo        = targeta.plazo_dias
    monto_cuota  = (monto_total / Decimal(plazo)).quantize(Decimal('0.01'))

    HORA_CORTE    = 20
    ahora         = timezone.localtime(timezone.now())
    dia_referencia = localdate()

    if ahora.hour >= HORA_CORTE:
        dia_referencia = dia_referencia + datetime.timedelta(days=1)

    for i in range(1, plazo + 1):
        vencimiento = dia_referencia + datetime.timedelta(days=i)

        if vencimiento.weekday() == 6:
            vencimiento = vencimiento + datetime.timedelta(days=1)

        Cuota.objects.create(
            targeta=targeta,
            numero=i,
            monto=monto_cuota,
            saldo_cuota=monto_cuota,
            fecha_vencimiento=vencimiento,
            estado='PENDIENTE'
        )

    targeta.actualizar_estado()


@login_required
def historial_abonos(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id)
    rol     = request.user.perfil.rol

    if rol == 'SUPERVISOR' and targeta.ruta.supervisor != request.user:
        messages.error(request, "No autorizado")
        return redirect('dashboard')

    if rol == 'TRABAJADOR' and request.user not in targeta.ruta.trabajadores.all():
        messages.error(request, "No autorizado")
        return redirect('dashboard')

    abonos = Abono.objects.filter(targeta=targeta).order_by('-fecha')

    total_abonado = abonos.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    return render(request, "app/historial_abonos.html", {
        "targeta":       targeta,
        "abonos":        abonos,
        "total_abonado": total_abonado
    })

@login_required
def eliminar_abono(request, abono_id):
    abono   = get_object_or_404(Abono, id=abono_id)
    targeta = abono.targeta
    ruta    = targeta.ruta

    if request.user != ruta.supervisor and not request.user.is_staff:
        messages.error(request, "No tienes permiso para eliminar abonos.")
        return redirect('historial_abonos', targeta_id=targeta.id)

    with transaction.atomic():
        if abono.cuota:
            cuota = abono.cuota
            cuota.saldo_cuota += abono.monto
            cuota.estado      = 'PENDIENTE'
            cuota.fecha_pago  = None
            cuota.save()

        ruta.base -= abono.monto
        ruta.save()

        MovimientoRuta.objects.create(
            ruta=ruta,
            tipo='EGRESO',
            monto=abono.monto,
            descripcion=f"ANULACIÓN ABONO - Cliente: {targeta.nombre_cliente} (Abono ID: {abono.id})"
        )

        abono.delete()
        targeta.actualizar_estado()

    messages.success(request, f"Abono eliminado. Se han devuelto ${abono.monto} a la deuda.")
    return redirect('historial_abonos', targeta_id=targeta.id)


# ================================================================================================================================================
# GASTOS
# ================================================================================================================================================


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

        ruta.base -= monto
        ruta.save(update_fields=['base'])

        messages.success(request, "Retiro registrado correctamente")
        return redirect('resumen_caja', ruta_id=ruta.id)

    return render(request, 'app/retiro_justificado.html', {'ruta': ruta})

@login_required
def registrar_gasto(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)
    hoy  = date.today()

    gastos_mes_qs = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        descripcion__startswith='GASTO:',
        fecha__month=hoy.month,
        fecha__year=hoy.year
    ).order_by('-fecha')

    total_gastos_mes = gastos_mes_qs.aggregate(Sum('monto'))['monto__sum'] or 0

    if request.method == 'POST':
        monto_str   = request.POST.get('monto')
        descripcion = request.POST.get('descripcion')

        try:
            if monto_str:
                monto = Decimal(monto_str)

                if monto <= 0:
                    messages.error(request, "El monto debe ser mayor a cero.")
                elif ruta.base < monto:
                    messages.error(request, f"⚠️ Fondos insuficientes. La base actual es ${ruta.base}")
                else:
                    with transaction.atomic():
                        ruta.base -= monto
                        ruta.save()

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

    return render(request, 'app/registrar_gasto.html', {
        'ruta':            ruta,
        'gastos_recientes': gastos_mes_qs,
        'total_gastos_mes': total_gastos_mes
    })


# ================================================================================================================================================
# RESUMEN MENSUAL
# ================================================================================================================================================

@login_required
@supervisor_required
def resumen_mensual(request, ruta_id):
    import calendar

    ruta = get_object_or_404(Ruta, id=ruta_id, supervisor=request.user)

    mes_param = request.GET.get('mes')
    hoy       = localdate()

    try:
        if mes_param:
            anio, mes = int(mes_param.split('-')[0]), int(mes_param.split('-')[1])
        else:
            anio, mes = hoy.year, hoy.month
    except Exception:
        anio, mes = hoy.year, hoy.month

    primer_dia    = datetime.date(anio, mes, 1)
    ultimo_dia    = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
    mes_param_str = f'{anio}-{str(mes).zfill(2)}'

    # ── Préstamos nuevos ──────────────────────────────────────────────────────
    prestamos_movs = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        descripcion__startswith='Préstamo otorgado',
        fecha__date__gte=primer_dia,
        fecha__date__lte=ultimo_dia,
    ).order_by('-fecha')

    total_prestamos = prestamos_movs.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    prestamos = []
    for mov in prestamos_movs:
        nombre = mov.descripcion.replace('Préstamo otorgado a ', '').strip()
        prestamos.append({
            'fecha':          mov.fecha,
            'nombre_cliente': nombre,
            'monto':          mov.monto,
        })

    # ── Renovaciones ──────────────────────────────────────────────────────────
    renovaciones_movs = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        descripcion__startswith='RENOVACIÓN',
        fecha__date__gte=primer_dia,
        fecha__date__lte=ultimo_dia,
    ).order_by('-fecha')

    total_renovaciones = renovaciones_movs.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    renovaciones = []
    for mov in renovaciones_movs:
        nombre = mov.descripcion.replace('RENOVACIÓN (Restauración):', '').strip()
        renovaciones.append({
            'fecha':          mov.fecha,
            'nombre_cliente': nombre,
            'monto':          mov.monto,
        })

    # ── Gastos ────────────────────────────────────────────────────────────────
    gastos_movs = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        descripcion__startswith='GASTO:',
        fecha__date__gte=primer_dia,
        fecha__date__lte=ultimo_dia,
    ).order_by('-fecha')

    total_gastos = gastos_movs.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    gastos = []
    for mov in gastos_movs:
        gastos.append({
            'fecha':       mov.fecha,
            'descripcion': mov.descripcion.replace('GASTO:', '').strip(),
            'monto':       mov.monto,
        })

    # ── Abonos cobrados ───────────────────────────────────────────────────────
    abonos_mes  = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__date__gte=primer_dia,
        fecha__date__lte=ultimo_dia,
    )
    total_abonos = abonos_mes.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    # ── Resumen ───────────────────────────────────────────────────────────────
    total_egresos = total_prestamos + total_renovaciones + total_gastos
    neto_mes      = total_abonos - total_egresos

    # ── Selector de meses ─────────────────────────────────────────────────────
    primer_mov = MovimientoRuta.objects.filter(ruta=ruta).order_by('fecha').first()
    meses_disponibles = []
    if primer_mov:
        cur = primer_mov.fecha.date().replace(day=1)
        fin = hoy.replace(day=1)
        while cur <= fin:
            meses_disponibles.append(cur)
            cur = cur.replace(month=cur.month + 1) if cur.month < 12 else cur.replace(year=cur.year + 1, month=1)
        meses_disponibles.reverse()

    return render(request, 'app/resumen_mensual.html', {
        'ruta':               ruta,
        'mes_actual':         primer_dia,
        'mes_param':          mes_param_str,
        'meses_disponibles':  meses_disponibles,
        'prestamos':          prestamos,
        'renovaciones':       renovaciones,
        'gastos':             gastos,
        'total_prestamos':    total_prestamos,
        'total_renovaciones': total_renovaciones,
        'total_gastos':       total_gastos,
        'total_abonos':       total_abonos,
        'total_egresos':      total_egresos,
        'neto_mes':           neto_mes,
        'es_mes_actual':      (anio == hoy.year and mes == hoy.month),
    })


# ================================================================================================================================================
# CAJAS
# ================================================================================================================================================


@login_required
def historial_cajas(request, ruta_id):
    import calendar

    ruta = get_object_or_404(Ruta, id=ruta_id)

    mes_param = request.GET.get('mes')
    hoy       = localdate()

    try:
        if mes_param:
            anio, mes = int(mes_param.split('-')[0]), int(mes_param.split('-')[1])
        else:
            anio, mes = hoy.year, hoy.month
    except Exception:
        anio, mes = hoy.year, hoy.month

    primer_dia    = datetime.date(anio, mes, 1)
    ultimo_dia    = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
    mes_param_str = f'{anio}-{str(mes).zfill(2)}'

    abonos_mes = (
        Abono.objects
        .filter(targeta__ruta=ruta, fecha__date__gte=primer_dia, fecha__date__lte=ultimo_dia)
        .values('fecha__date')
        .annotate(total=Sum('monto'))
    )
    abonos_por_dia = {a['fecha__date']: a['total'] for a in abonos_mes}

    egresos_mes = (
        MovimientoRuta.objects
        .filter(ruta=ruta, tipo='EGRESO', fecha__date__gte=primer_dia, fecha__date__lte=ultimo_dia)
        .values('fecha__date')
        .annotate(total=Sum('monto'))
    )
    egresos_por_dia = {e['fecha__date']: e['total'] for e in egresos_mes}

    dias_con_actividad = sorted(
        set(list(abonos_por_dia.keys()) + list(egresos_por_dia.keys())),
        reverse=True
    )

    dias = []
    for dia in dias_con_actividad:
        ingresos_dia = abonos_por_dia.get(dia, Decimal('0.00'))
        egresos_dia  = egresos_por_dia.get(dia, Decimal('0.00'))

        movimientos = []

        for a in Abono.objects.filter(targeta__ruta=ruta, fecha__date=dia).select_related('targeta').order_by('fecha'):
            movimientos.append({
                'tipo':        'INGRESO',
                'descripcion': f'Abono — {a.targeta.nombre_cliente}',
                'monto':       a.monto,
                'hora':        a.fecha,
            })

        for e in MovimientoRuta.objects.filter(ruta=ruta, tipo='EGRESO', fecha__date=dia).order_by('fecha'):
            movimientos.append({
                'tipo':        'EGRESO',
                'descripcion': e.descripcion,
                'monto':       e.monto,
                'hora':        e.fecha,
            })

        movimientos.sort(key=lambda x: x['hora'])

        dias.append({
            'fecha':      dia,
            'ingresos':   ingresos_dia,
            'egresos':    egresos_dia,
            'neto':       ingresos_dia - egresos_dia,
            'movimientos': movimientos,
        })

    total_ingresos_mes = sum(d['ingresos'] for d in dias)
    total_egresos_mes  = sum(d['egresos']  for d in dias)
    neto_mes           = total_ingresos_mes - total_egresos_mes

    primer_abono = Abono.objects.filter(targeta__ruta=ruta).order_by('fecha').first()
    meses_disponibles = []
    if primer_abono:
        cur = primer_abono.fecha.date().replace(day=1)
        fin = hoy.replace(day=1)
        while cur <= fin:
            meses_disponibles.append(cur)
            cur = cur.replace(month=cur.month + 1) if cur.month < 12 else cur.replace(year=cur.year + 1, month=1)
        meses_disponibles.reverse()

    return render(request, 'app/historial_cajas.html', {
        'ruta':               ruta,
        'dias':               dias,
        'mes_actual':         primer_dia,
        'total_ingresos_mes': total_ingresos_mes,
        'total_egresos_mes':  total_egresos_mes,
        'neto_mes':           neto_mes,
        'meses_disponibles':  meses_disponibles,
        'mes_param':          mes_param_str,
    })


def cerrar_cajas_anteriores(ruta):
    hoy = localdate()

    cajas_abiertas = CajaRuta.objects.filter(ruta=ruta, cerrada=False).exclude(fecha=hoy)

    for caja in cajas_abiertas:
        ingresos = Abono.objects.filter(
            targeta__ruta=ruta, fecha__date=caja.fecha
        ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

        egresos = MovimientoRuta.objects.filter(
            ruta=ruta, tipo="EGRESO", fecha__date=caja.fecha
        ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

        caja.ingresos    = ingresos
        caja.egresos     = egresos
        caja.saldo_final = caja.saldo_inicial + ingresos - egresos
        caja.cerrada     = True
        caja.save()

@login_required
def movimientos_ruta(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if request.user != ruta.supervisor:
        messages.error(request, "No autorizado")
        return redirect("dashboard")

    hoy = localdate()

    try:
        from django.core.management import call_command
        call_command('cerrar_cajas')
    except Exception as e:
        print(f"Error en cierre automático: {e}")

    ruta.refresh_from_db()

    caja, created = CajaRuta.objects.get_or_create(
        ruta=ruta,
        fecha=hoy,
        defaults={"saldo_inicial": ruta.base}
    )

    abonos = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__gte=hoy,
        fecha__lt=hoy + timedelta(days=1)
    )
    ingresos_hoy = abonos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    egresos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo="EGRESO",
        fecha__gte=hoy,
        fecha__lt=hoy + timedelta(days=1)
    )
    egresos_hoy = egresos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    caja.ingresos = ingresos_hoy
    caja.egresos  = egresos_hoy
    caja.save()

    saldo_hoy = caja.saldo_inicial + ingresos_hoy - egresos_hoy

    movimientos = []
    for a in abonos:
        movimientos.append({"fecha": a.fecha, "tipo": "INGRESO", "monto": a.monto, "descripcion": f"Abono - {a.targeta.nombre_cliente}"})
    for e in egresos:
        movimientos.append({"fecha": e.fecha, "tipo": "EGRESO",  "monto": e.monto, "descripcion": e.descripcion})
    movimientos.sort(key=lambda x: x["fecha"], reverse=True)

    return render(request, "app/movimientos_ruta.html", {
        "ruta":         ruta,
        "caja":         caja,
        "movimientos":  movimientos,
        "ingresos_hoy": ingresos_hoy,
        "egresos_hoy":  egresos_hoy,
        "saldo_hoy":    saldo_hoy,
    })

@login_required
def reporte_diario(request, ruta_id, fecha):
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if request.user != ruta.supervisor:
        return redirect("dashboard")

    try:
        fecha_reporte = datetime.datetime.strptime(fecha, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return redirect("dashboard_supervisor")

    inicio_dia = make_aware(datetime.datetime.combine(fecha_reporte, datetime.time.min))
    fin_dia    = make_aware(datetime.datetime.combine(fecha_reporte, datetime.time.max))
    hoy        = localdate()

    caja, created = CajaRuta.objects.get_or_create(
        ruta=ruta,
        fecha=fecha_reporte,
        defaults={'saldo_inicial': ruta.base, 'cerrada': False}
    )

    abonos  = Abono.objects.filter(targeta__ruta=ruta, fecha__range=(inicio_dia, fin_dia)).order_by("fecha")
    egresos = MovimientoRuta.objects.filter(ruta=ruta, tipo="EGRESO", fecha__range=(inicio_dia, fin_dia)).order_by("fecha")

    total_ingresos = abonos.aggregate(total=Sum("monto"))["total"]  or Decimal("0.00")
    total_egresos  = egresos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    caja.ingresos    = total_ingresos
    caja.egresos     = total_egresos
    caja.saldo_final = caja.saldo_inicial + total_ingresos - total_egresos
    if fecha_reporte < hoy:
        caja.cerrada = True
    caja.save()

    return render(request, "app/reporte_diario.html", {
        "ruta":           ruta,
        "fecha":          fecha_reporte,
        "caja":           caja,
        "abonos":         abonos,
        "egresos":        egresos,
        "total_ingresos": total_ingresos,
        "total_egresos":  total_egresos,
        "saldo_inicial":  caja.saldo_inicial,
        "saldo_final":    caja.saldo_final,
    })

def historial_cierres(request, ruta_id):
    ruta      = get_object_or_404(Ruta, id=ruta_id)
    historial = ReporteDiario.objects.filter(ruta=ruta).order_by('-fecha')

    for registro in historial:
        registro.movimientos_del_dia = MovimientoRuta.objects.filter(
            ruta=ruta, fecha__date=registro.fecha
        ).order_by('fecha')

    return render(request, 'app/historial_cierres.html', {
        'ruta':      ruta,
        'historial': historial
    })


# ================================================================================================================================================
# MAPA
# ================================================================================================================================================


def mapa_clientes(request, ruta_id):
    ruta     = get_object_or_404(Ruta, id=ruta_id)
    clientes = Targeta.objects.filter(ruta=ruta).exclude(latitud=None).exclude(longitud=None)

    return render(request, 'app/mapa_clientes.html', {
        'ruta':     ruta,
        'clientes': clientes
    })

def guardar_gps_cliente(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id)

    if request.method == 'POST':
        lat = request.POST.get('latitud')
        lng = request.POST.get('longitud')

        targeta.latitud      = lat
        targeta.longitud     = lng
        targeta.direccion_casa = f"https://www.google.com/maps?q={lat},{lng}"
        targeta.save()

        return JsonResponse({'status': 'success'})

def validar_gps_cliente(request, pk):
    targeta = get_object_or_404(Targeta, pk=pk)

    if request.method == 'POST':
        lat = request.POST.get('latitud')
        lng = request.POST.get('longitud')

        if lat and lng:
            targeta.latitud      = float(lat)
            targeta.longitud     = float(lng)
            targeta.direccion_casa = f"https://www.google.com/maps?q={lat},{lng}"
            targeta.save()

            return JsonResponse({'status': 'ok', 'message': 'Ubicación guardada correctamente'})

    return render(request, 'app/validar_gps.html', {'targeta': targeta})