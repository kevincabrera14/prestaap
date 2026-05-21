# ===============================================================================================================================================================
# import
# ===============================================================================================================================================================

from django.utils.timezone import localtime, make_aware, get_current_timezone, localdate, now
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .permissions import supervisor_required
from .models import (
    Ruta, Targeta, MovimientoRuta, CajaRuta, Cuota,
    GastoTrabajador, HistorialRuta, Abono
)
from django.contrib import messages
from django.db.models import Sum, Q, F, Count
from django.db import transaction
from decimal import Decimal
import datetime
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import user_passes_test
from django.urls import reverse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from datetime import date, timedelta
from django.utils import timezone
import json
import google.generativeai as genai
from django.conf import settings
from django.views.decorators.http import require_POST


# ===============================================================================================================================================================
# AUTH
# ===============================================================================================================================================================

def informacion(request):
    return render(request, 'app/informacion.html')

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
@login_required
@supervisor_required
def dashboard_supervisor(request):
    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.rol == 'SUPERVISOR':
        rutas = Ruta.objects.filter(supervisor=request.user)
    elif perfil and perfil.rol == 'TRABAJADOR':
        rutas = Ruta.objects.filter(trabajadores=request.user)
    else:
        rutas = Ruta.objects.none()

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

    hoy = localdate()
    hoy_inicio_aware = make_aware(datetime.datetime.combine(hoy, datetime.time.min))
    hoy_fin_aware    = make_aware(datetime.datetime.combine(hoy, datetime.time.max))

    targetas = []
    for t in targetas_qs:
        if t.saldo_restante <= 0:
            continue

        todas_las_cuotas = t.cuotas.all()
        t.cuotas_pagadas = sum(1 for c in todas_las_cuotas if c.estado == 'PAGADA')
        t.total_cuotas   = len(todas_las_cuotas)

        t.abono_hoy = t.abonos.filter(
            fecha__gte=hoy_inicio_aware,
            fecha__lte=hoy_fin_aware
        ).exists()

        ultimo_abono = t.abonos.order_by('-fecha').first()
        if ultimo_abono:
            t.dias_sin_abono = (hoy - ultimo_abono.fecha.date()).days
        else:
            t.dias_sin_abono = (hoy - t.fecha_creacion).days

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

    # ── ruta seleccionada ──────────────────────────────────────────────
    ruta_sel = Ruta.objects.filter(id=ruta_id).first() if ruta_id else None

    resumen = {
    "total_clientes": len(targetas),
    "en_mora":        sum(1 for t in targetas if t.estado == "MORA"),
    "total_saldo":    sum(t.saldo_restante for t in targetas),
    "dinero_en_ruta": sum(t.saldo_restante for t in targetas),
    }

    return render(request, "app/supervisor.html", {
        "rutas":    rutas,
        "targetas": targetas,
        "resumen":  resumen,
        "ruta_sel": ruta_sel,   # <-- ahora es el objeto completo con .base y .dinero_en_ruta
    })

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
    hoy = localdate()
    hoy_inicio_aware = make_aware(datetime.datetime.combine(hoy, datetime.time.min))
    hoy_fin_aware    = make_aware(datetime.datetime.combine(hoy, datetime.time.max))

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
            t.dias_sin_abono = (hoy - ultimo_abono.fecha.date()).days
        else:
            t.dias_sin_abono = (hoy - t.fecha_creacion).days

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

# --------------------------------------------------------------------
# NUEVAS VISTAS SOLICITADAS
# --------------------------------------------------------------------
@login_required
def agregar_gasto(request):
    """Vista para que un trabajador registre un gasto propio."""
    if request.method == "POST":
        monto_str = request.POST.get('monto')
        descripcion = request.POST.get('descripcion', '')
        try:
            monto = Decimal(monto_str)
            if monto <= 0:
                messages.error(request, "El monto debe ser mayor a cero.")
                return redirect('agregar_gasto')
            GastoTrabajador.objects.create(
                trabajador=request.user,
                monto=monto,
                descripcion=descripcion,
            )
            messages.success(request, f"Gasto de ${monto} registrado.")
            return redirect('dashboard_trabajador')
        except Exception as e:
            messages.error(request, f"Error al registrar el gasto: {e}")

    return render(request, 'app/agregar_gasto.html', {})

@login_required
def historial_ruta(request, ruta_id):
    """Muestra el historial de abonos, gastos y préstamos del trabajador por día."""
    # Get the specific route, ensure the user is a worker on it
    ruta = get_object_or_404(Ruta, id=ruta_id, trabajadores=request.user)

    # All routes assigned to the worker (used for filtering gastos and prestamos)
    rutas_trabajador = Ruta.objects.filter(trabajadores=request.user)

    hoy = localdate()
    start_date = hoy - datetime.timedelta(days=30)
    start_dt = make_aware(datetime.datetime.combine(start_date, datetime.time.min))
    end_dt = make_aware(datetime.datetime.combine(hoy, datetime.time.max))

    # Prepare dict to hold data per day
    dias_dict = {}

    # ABONOS: filtered by worker and their routes
    abonos_qs = Abono.objects.filter(
        targeta__ruta__in=rutas_trabajador,
        registrado_por=request.user,
        fecha__range=(start_dt, end_dt)
    ).select_related('targeta')
    for a in abonos_qs.order_by('fecha'):
        d = a.fecha.date()
        entry = dias_dict.setdefault(d, {
            'fecha': d,
            'abonos': [],
            'gastos': [],
            'prestamos': [],
            'total_abonos': Decimal('0.00'),
            'total_gastos': Decimal('0.00'),
            'total_prestamos': Decimal('0.00'),
            'count_abonos': 0,
            'count_gastos': 0,
            'count_prestamos': 0,
        })
        entry['abonos'].append({
            'cliente': a.targeta.nombre_cliente,
            'monto': a.monto,
            'hora': a.fecha,
            'usuario': a.registrado_por.username if a.registrado_por else None,
        })
        entry['total_abonos'] += a.monto
        entry['count_abonos'] += 1

    # GASTOS: MovimientoRuta tipo EGRESO en las rutas del trabajador
    gastos_qs = MovimientoRuta.objects.filter(
        ruta__in=rutas_trabajador,
        tipo='EGRESO',
        descripcion__startswith='GASTO:',
        fecha__range=(start_dt, end_dt)
    )
    for g in gastos_qs.order_by('fecha'):
        d = g.fecha.date()
        entry = dias_dict.setdefault(d, {
            'fecha': d,
            'abonos': [],
            'gastos': [],
            'prestamos': [],
            'total_abonos': Decimal('0.00'),
            'total_gastos': Decimal('0.00'),
            'total_prestamos': Decimal('0.00'),
            'count_abonos': 0,
            'count_gastos': 0,
            'count_prestamos': 0,
        })
        entry['gastos'].append({
            'descripcion': g.descripcion.replace('GASTO:', '').strip(),
            'monto': g.monto,
            'hora': g.fecha,
        })
        entry['total_gastos'] += g.monto
        entry['count_gastos'] += 1

    # PRESTAMOS: Targetas creadas en las rutas del trabajador (fecha_creacion is a DateField)
    prestamos_qs = Targeta.objects.filter(
        ruta__in=rutas_trabajador,
        fecha_creacion__range=(start_date, hoy)
    )
    for p in prestamos_qs:
        d = p.fecha_creacion
        entry = dias_dict.setdefault(d, {
            'fecha': d,
            'abonos': [],
            'gastos': [],
            'prestamos': [],
            'total_abonos': Decimal('0.00'),
            'total_gastos': Decimal('0.00'),
            'total_prestamos': Decimal('0.00'),
            'count_abonos': 0,
            'count_gastos': 0,
            'count_prestamos': 0,
        })
        entry['prestamos'].append({
            'nombre_cliente': p.nombre_cliente,
            'monto_base': p.monto_base,
            'hora': p.fecha_creacion,
        })
        entry['total_prestamos'] += p.monto_base
        entry['count_prestamos'] += 1

# Convert dict to sorted list (most recent first)
    dias = sorted(dias_dict.values(), key=lambda x: x['fecha'], reverse=True)

    # Calcular saldo inicial y final por día basado en ruta.base actual
    # y los movimientos posteriores a cada día
    for dia_entry in dias:
        fecha_dia = dia_entry['fecha']
        inicio_dia_dt = make_aware(datetime.datetime.combine(fecha_dia, datetime.time.min))
        fin_dia_dt    = make_aware(datetime.datetime.combine(fecha_dia, datetime.time.max))

        # Abonos posteriores a este día
        abonos_post = Abono.objects.filter(
            targeta__ruta__in=rutas_trabajador,
            fecha__gt=fin_dia_dt
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

        # Movimientos posteriores
        mov_ing_post = MovimientoRuta.objects.filter(
            ruta__in=rutas_trabajador,
            tipo='INGRESO',
            fecha__gt=fin_dia_dt
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

        mov_egr_post = MovimientoRuta.objects.filter(
            ruta__in=rutas_trabajador,
            tipo='EGRESO',
            fecha__gt=fin_dia_dt
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

        # Saldo final del día = base actual menos lo que cambió después
        saldo_final_dia = ruta.base - abonos_post - mov_ing_post + mov_egr_post

        # Neto del día
        neto_dia = dia_entry['total_abonos'] - dia_entry['total_gastos'] - dia_entry['total_prestamos']

        # Saldo inicial = saldo final menos el neto
        saldo_inicial_dia = saldo_final_dia - neto_dia

        dia_entry['saldo_inicial'] = saldo_inicial_dia
        dia_entry['saldo_final']   = saldo_final_dia
        dia_entry['neto_dia']      = neto_dia

    context = {
        'ruta': ruta,
        'dias': dias,
    }
    return render(request, 'app/historial_trabajador.html', context)

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
def crear_targeta(request):
    # Determine routes based on user role
    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.rol == 'SUPERVISOR':
        rutas = Ruta.objects.filter(supervisor=request.user)
    elif perfil and perfil.rol == 'TRABAJADOR':
        rutas = Ruta.objects.filter(trabajadores=request.user)
    else:
        rutas = Ruta.objects.none()

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
            creada_por=request.user,
            abonos_offset=Decimal('0.00'),
        )

        crear_cuotas(targeta)

        MovimientoRuta.objects.create(
            ruta=ruta,
            tipo='EGRESO',
            monto=monto,
            descripcion=f'Préstamo otorgado a {targeta.nombre_cliente}',
            registrado_por=request.user,          # ← NUEVO
        )

        messages.success(request, "Tarjeta creada correctamente")
        return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

    return render(request, 'app/crear_targeta.html', {'rutas': rutas})

@login_required
@supervisor_required
def editar_targeta(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    # Determine routes based on user role
    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.rol == 'SUPERVISOR':
        rutas = Ruta.objects.filter(supervisor=request.user)
    elif perfil and perfil.rol == 'TRABAJADOR':
        rutas = Ruta.objects.filter(trabajadores=request.user)
    else:
        rutas = Ruta.objects.none()

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
                    descripcion=f"ELIMINACIÓN TARJETA (Pérdida) - Cliente: {nombre_cliente}",
                    registrado_por=request.user,      # ← NUEVO
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
                abonos_actuales = targeta.abonos.aggregate(
                    total=Sum('monto')
                )['total'] or Decimal('0.00')
                targeta.abonos_offset = abonos_actuales

                targeta.cuotas.all().delete()

                targeta.monto_base   = monto
                targeta.tasa_interes = tasa
                targeta.plazo_dias   = plazo
                targeta.estado       = 'PAGO'
                targeta.save()

                crear_cuotas(targeta)

                ruta.base -= monto
                ruta.save(update_fields=['base'])

                MovimientoRuta.objects.create(
                    ruta=ruta,
                    tipo='EGRESO',
                    monto=monto,
                    descripcion=f"RENOVACIÓN (Restauración): {targeta.nombre_cliente}",
                    registrado_por=request.user,      # ← NUEVO
                )

            messages.success(request, f"Crédito restaurado para {targeta.nombre_cliente}")
            return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

        except Exception as e:
            messages.error(request, f"Error: {e}")

    return render(request, "app/renovar_targeta.html", {"targeta": targeta})

@login_required
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

        if not cuotas_pendientes.exists():
            if targeta.saldo_restante <= 0:
                targeta.estado = 'PAGADA'
                targeta.save(update_fields=['estado'])
                messages.info(request, f"La tarjeta de {targeta.nombre_cliente} ya está saldada.")
            else:
                messages.error(request, "No hay cuotas pendientes para registrar el abono. Verifique el estado de la tarjeta.")
            return redirect(request.path)

        try:
            monto_recibido = Decimal(monto_input) if monto_input and Decimal(monto_input) > 0 else Decimal(0)
        except (ValueError, TypeError, Exception):
            monto_recibido = Decimal(0)

        cuota_inicio = None
        if monto_recibido <= 0 and cuota_id:
            cuota_inicio   = get_object_or_404(Cuota, id=cuota_id)
            monto_recibido = cuota_inicio.saldo_cuota

        if monto_recibido <= 0:
            messages.error(request, "Debe seleccionar una cuota o ingresar un monto.")
            return redirect(request.path)

        saldo_actual_targeta = targeta.saldo_restante
        if monto_recibido > saldo_actual_targeta:
            monto_recibido = saldo_actual_targeta

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
            monto_por_distribuir = monto_recibido
            for cuota in cuotas_a_procesar:
                if monto_por_distribuir <= 0:
                    break

                saldo_cuota_actual = cuota.saldo_cuota if cuota.saldo_cuota is not None else Decimal('0.00')
                if saldo_cuota_actual <= 0:
                    continue

                pago_a_cuota       = min(saldo_cuota_actual, monto_por_distribuir)
                cuota.saldo_cuota  = saldo_cuota_actual - pago_a_cuota
                if cuota.saldo_cuota <= 0:
                    cuota.estado      = 'PAGADA'
                    cuota.saldo_cuota = Decimal('0.00')
                    cuota.fecha_pago  = now()
                cuota.save()

                Abono.objects.create(
                    targeta=targeta,
                    cuota=cuota,
                    monto=pago_a_cuota,
                    registrado_por=request.user
                )
                monto_por_distribuir -= pago_a_cuota

            ruta.base += monto_original
            ruta.save(update_fields=['base'])

            MovimientoRuta.objects.create(
                ruta=ruta, tipo='INGRESO', monto=monto_original,
                descripcion=f"Abono - Cliente: {targeta.nombre_cliente}",
                registrado_por=request.user,          # ← NUEVO
            )

            targeta.refresh_from_db()
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
    monto_total  = targeta.monto_total
    plazo        = targeta.plazo_dias
    monto_cuota  = (monto_total / Decimal(plazo)).quantize(Decimal('0.01'))

    HORA_CORTE     = 20
    ahora          = timezone.localtime(timezone.now())
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

    targeta.refresh_from_db()
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
            descripcion=f"ANULACIÓN ABONO - Cliente: {targeta.nombre_cliente} (Abono ID: {abono.id})",
            registrado_por=request.user,          # ← NUEVO
        )

        abono.delete()
        targeta.refresh_from_db()
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

    # Adjust gastos visibility for workers
    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.rol == 'TRABAJADOR':
        gastos_mes_qs = MovimientoRuta.objects.filter(
            ruta=ruta,
            tipo='EGRESO',
            descripcion__startswith='GASTO:',
            fecha__month=hoy.month,
            fecha__year=hoy.year,
            ruta__trabajadores=request.user,
        ).order_by('-fecha')

    # Compute total gastos for the selected queryset
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
                            descripcion=f"GASTO: {descripcion}",
                            registrado_por=request.user,  # ← NUEVO
                        )

                    messages.success(request, f"✅ Gasto de ${monto} descontado de la base.")
                    return redirect(f'/dashboard/supervisor/?ruta={ruta.id}')
            else:
                messages.error(request, "El monto es obligatorio.")

        except Exception as e:
            messages.error(request, f"Error al procesar el gasto: {e}")

    return render(request, 'app/registrar_gasto.html', {
        'ruta': ruta,
        'gastos_recientes': gastos_mes_qs,
        'total_gastos_mes': total_gastos_mes
    })

# ================================================================================================================================================
# AGREGAR CAPITAL A LA BASE DE LA RUTA
# ================================================================================================================================================

@login_required
@supervisor_required
def agregar_capital(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id, supervisor=request.user)

    # Historial de ingresos de capital para mostrar en la vista
    capital_reciente = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='INGRESO',
        descripcion__startswith='CAPITAL:'
    ).order_by('-fecha')[:10]

    if request.method == "POST":
        monto_str   = request.POST.get("monto", "").strip()
        observacion = request.POST.get("observacion", "").strip() or "Ingreso de capital"

        try:
            monto = Decimal(monto_str)

            if monto <= 0:
                messages.error(request, "El monto debe ser mayor a cero.")
                return redirect(request.path)

            with transaction.atomic():
                ruta.base += monto
                ruta.save(update_fields=["base"])

                MovimientoRuta.objects.create(
                    ruta=ruta,
                    tipo="INGRESO",
                    monto=monto,
                    descripcion=f"CAPITAL: {observacion}",
                    registrado_por=request.user,          # ← NUEVO
                )

            messages.success(request, f"✅ Se agregaron ${monto} a la base de la ruta.")
            return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")

        except (ValueError, TypeError):
            messages.error(request, "Ingresa un monto numérico válido.")
        except Exception as e:
            messages.error(request, f"Error al procesar: {e}")

    return render(request, "app/agregar_capital.html", {
        "ruta": ruta,
        "capital_reciente": capital_reciente,
    })

# ================================================================================================================================================
# CAJAS
# ================================================================================================================================================

@login_required
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

    abonos_por_dia_agg = {
        a['fecha__date']: a['total']
        for a in Abono.objects
            .filter(targeta__ruta=ruta, fecha__date__gte=primer_dia, fecha__date__lte=ultimo_dia)
            .values('fecha__date')
            .annotate(total=Sum('monto'))
    }
    egresos_por_dia_agg = {
        e['fecha__date']: e['total']
        for e in MovimientoRuta.objects
            .filter(ruta=ruta, tipo='EGRESO', fecha__date__gte=primer_dia, fecha__date__lte=ultimo_dia)
            .values('fecha__date')
            .annotate(total=Sum('monto'))
    }
    capital_por_dia_agg = {
        c['fecha__date']: c['total']
        for c in MovimientoRuta.objects
            .filter(ruta=ruta, tipo='INGRESO', descripcion__startswith='CAPITAL:', fecha__date__gte=primer_dia, fecha__date__lte=ultimo_dia)
            .values('fecha__date')
            .annotate(total=Sum('monto'))
    }
    dias_con_actividad = sorted(
        set(
            list(abonos_por_dia_agg.keys()) +
            list(egresos_por_dia_agg.keys()) +
            list(capital_por_dia_agg.keys())
        ),
        reverse=True
    )

    dias = []
    for dia in dias_con_actividad:
        abonos_qs = (
            Abono.objects
                .filter(targeta__ruta=ruta, fecha__date=dia)
                .select_related('targeta', 'registrado_por')
                .order_by('fecha')
        )
        abonos = [
            {
                'cliente': a.targeta.nombre_cliente,
                'monto':   a.monto,
                'hora':    a.fecha,
                'usuario': a.registrado_por.username if a.registrado_por else None,
            }
            for a in abonos_qs
        ]
        total_abonos = sum(a['monto'] for a in abonos)

        capital_qs = MovimientoRuta.objects.filter(
            ruta=ruta,
            tipo='INGRESO',
            descripcion__startswith='CAPITAL:',
            fecha__date=dia
        ).select_related('registrado_por').order_by('fecha')   # ← NUEVO select_related
        capital_list = [
            {
                'descripcion': mov.descripcion.replace('CAPITAL:', '').strip(),
                'monto':       mov.monto,
                'hora':        mov.fecha,
                'usuario':     mov.registrado_por.username if mov.registrado_por else None,  # ← NUEVO
            }
            for mov in capital_qs
        ]
        total_capital_dia = sum(m['monto'] for m in capital_list)

        prestamos    = []
        renovaciones = []
        gastos       = []

        for mov in MovimientoRuta.objects.filter(
            ruta=ruta, tipo='EGRESO', fecha__date=dia
        ).select_related('registrado_por').order_by('fecha'):   # ← NUEVO select_related
            desc = mov.descripcion or ''
            base = {
                'monto_base': mov.monto,
                'hora':       mov.fecha,
                'usuario':    mov.registrado_por.username if mov.registrado_por else None,  # ← NUEVO
            }
            if desc.startswith('Préstamo otorgado'):
                prestamos.append({**base, 'nombre_cliente': desc.replace('Préstamo otorgado a ', '').strip()})
            elif 'RENOVACIÓN' in desc:
                renovaciones.append({**base, 'nombre_cliente': desc.replace('RENOVACIÓN (Restauración):', '').strip()})
            else:
                gastos.append({**base, 'descripcion': desc.replace('GASTO:', '').strip()})

        total_prestamos = sum(m['monto_base'] for m in prestamos)
        total_renovaciones = sum(m['monto_base'] for m in renovaciones)
        total_gastos = sum(m['monto_base'] for m in gastos)
        total_egresos_dia  = total_prestamos + total_renovaciones + total_gastos

        neto_dia = total_abonos + total_capital_dia - total_egresos_dia

        dias.append({
            'fecha': dia,
            'ingresos': total_abonos + total_capital_dia,
            'egresos': total_egresos_dia,
            'neto': neto_dia,
            'total_movimientos': len(abonos) + len(capital_list) + len(prestamos) + len(renovaciones) + len(gastos),
            'abonos': abonos,
            'capital': capital_list,
            'prestamos': prestamos,
            'renovaciones': renovaciones,
            'gastos': gastos,
            'total_abonos': total_abonos,
            'total_capital_dia': total_capital_dia,
            'total_prestamos': total_prestamos,
            'total_renovaciones': total_renovaciones,
            'total_gastos': total_gastos,
        })

    total_ingresos_mes = sum(d['total_abonos'] for d in dias)
    total_capital_mes = sum(d['total_capital_dia'] for d in dias)
    total_egresos_mes = sum(d['egresos'] for d in dias)
    neto_mes = total_ingresos_mes + total_capital_mes - total_egresos_mes

    total_prestamos_mes = sum(sum(m['monto_base'] for m in d['prestamos']) for d in dias)
    total_renovaciones_mes = sum(sum(m['monto_base'] for m in d['renovaciones']) for d in dias)
    total_gastos_mes = sum(sum(m['monto_base'] for m in d['gastos']) for d in dias)
    total_capital_total = total_prestamos_mes + total_renovaciones_mes
    total_perdidas_mes = total_egresos_mes - total_capital_total - total_gastos_mes

    primer_abono = Abono.objects.filter(targeta__ruta=ruta).order_by('fecha').first()
    meses_disponibles = []
    if primer_abono:
        cur = primer_abono.fecha.date().replace(day=1)
        fin = hoy.replace(day=1)
        while cur <= fin:
            meses_disponibles.append(cur)
            cur = (
                cur.replace(month=cur.month + 1)
                if cur.month < 12
                else cur.replace(year=cur.year + 1, month=1)
            )
        meses_disponibles.reverse()

    return render(request, 'app/historial_cajas.html', {
        'ruta': ruta,
        'dias': dias,
        'mes_actual': primer_dia,
        'total_ingresos_mes': total_ingresos_mes,
        'total_capital_mes': total_capital_mes,
        'total_egresos_mes': total_egresos_mes,
        'total_capital_total': total_capital_total,
        'total_prestamos_mes': total_prestamos_mes,
        'total_renovaciones_mes': total_renovaciones_mes,
        'total_gastos_mes': total_gastos_mes,
        'total_perdidas_mes': total_perdidas_mes,
        'neto_mes': neto_mes,
        'meses_disponibles': meses_disponibles,
        'mes_param': mes_param_str,
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
    ingresos_hoy = abonos.aggregate(total=Sum("monto"))['total'] or Decimal('0.00')

    egresos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo="EGRESO",
        fecha__gte=hoy,
        fecha__lt=hoy + timedelta(days=1)
    )
    egresos_hoy = egresos.aggregate(total=Sum("monto"))['total'] or Decimal('0.00')

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
        "ruta": ruta,
        "caja": caja,
        "movimientos": movimientos,
        "ingresos_hoy": ingresos_hoy,
        "egresos_hoy": egresos_hoy,
        "saldo_hoy": saldo_hoy,
    })

# ================================================================================================================================================
# REPORTE DIARIO
# ================================================================================================================================================

@login_required
def reporte_diario(request, ruta_id, fecha):
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if request.user != ruta.supervisor:
        return redirect('dashboard')

    try:
        fecha_reporte = datetime.datetime.strptime(fecha, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return redirect('dashboard_supervisor')

    inicio_dia = make_aware(datetime.datetime.combine(fecha_reporte, datetime.time.min))
    fin_dia    = make_aware(datetime.datetime.combine(fecha_reporte, datetime.time.max))
    hoy        = localdate()

    # ── Abonos del día ──────────────────────────────────────────────────────
    abonos = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__range=(inicio_dia, fin_dia)
    ).order_by("fecha")
    total_ingresos = abonos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # ── Capital inyectado del día ────────────────────────────────────────────
    capital_ingresos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='INGRESO',
        descripcion__startswith='CAPITAL:',
        fecha__range=(inicio_dia, fin_dia)
    ).order_by("fecha")
    total_capital_dia = capital_ingresos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # ── Egresos del día clasificados ─────────────────────────────────────────
    egresos_qs = MovimientoRuta.objects.filter(
        ruta=ruta, tipo="EGRESO", fecha__range=(inicio_dia, fin_dia)
    )
    egresos_gastos       = egresos_qs.filter(descripcion__startswith="GASTO:").order_by("fecha")
    egresos_prestamos    = egresos_qs.filter(descripcion__startswith="Préstamo otorgado").order_by("fecha")
    egresos_renovaciones = egresos_qs.filter(descripcion__startswith="RENOVACIÓN").order_by("fecha")
    egresos_otros        = egresos_qs.exclude(
        descripcion__startswith="GASTO:"
    ).exclude(
        descripcion__startswith="Préstamo otorgado"
    ).exclude(
        descripcion__startswith="RENOVACIÓN"
    ).order_by("fecha")

    total_gastos           = egresos_gastos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")
    total_prestamos_dia    = egresos_prestamos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")
    total_renovaciones_dia = egresos_renovaciones.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")
    total_otros            = egresos_otros.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")
    total_egresos          = total_gastos + total_prestamos_dia + total_renovaciones_dia + total_otros

    # ── LÓGICA DE SALDO FINAL Y SALDO INICIAL — siempre anclados a ruta.base ─────────
    # Paso 1: Calcular la suma neta de todos los movimientos DESPUÉS de esta fecha
    # Abonos cobrados después de esta fecha (suman a base)
    abonos_posteriores = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__gt=fin_dia
    ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # MovimientosRuta después de esta fecha
    mov_ingresos_posteriores = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='INGRESO',
        fecha__gt=fin_dia
    ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    mov_egresos_posteriores = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        fecha__gt=fin_dia
    ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # Saldo final del día = base actual menos lo que cambió después de ese día
    saldo_final = (
        ruta.base
        - abonos_posteriores
        - mov_ingresos_posteriores
        + mov_egresos_posteriores
    )

    # Saldo inicial del día = saldo final menos el neto de ese día
    neto_dia = (total_ingresos + total_capital_dia) - total_egresos
    saldo_inicial = saldo_final - neto_dia

    # ── Guardar / actualizar CajaRuta ────────────────────────────────────────
    caja, created = CajaRuta.objects.get_or_create(
        ruta=ruta,
        fecha=fecha_reporte,
        defaults={
            "saldo_inicial": saldo_inicial,
            "ingresos":      total_ingresos + total_capital_dia,
            "egresos":       total_egresos,
            "saldo_final":   saldo_final,
        }
    )

    if not created:
        caja.saldo_inicial = saldo_inicial
        caja.ingresos      = total_ingresos + total_capital_dia
        caja.egresos       = total_egresos
        caja.saldo_final   = saldo_final
        if fecha_reporte < hoy:
            caja.cerrada = True
        caja.save()

    return render(request, "app/reporte_diario.html", {
        "ruta":                  ruta,
        "fecha":                 fecha_reporte,
        "caja":                  caja,
        "abonos":                abonos,
        "total_ingresos":        total_ingresos,
        "capital_ingresos":      capital_ingresos,
        "total_capital_dia":     total_capital_dia,
        "egresos_gastos":        egresos_gastos,
        "egresos_prestamos":     egresos_prestamos,
        "egresos_renovaciones": egresos_renovaciones,
        "renovaciones": egresos_renovaciones,
        "egresos_otros":         egresos_otros,
        "total_gastos":          total_gastos,
        "total_prestamos_dia":   total_prestamos_dia,
        "total_renovaciones_dia":total_renovaciones_dia,
        "total_egresos":         total_egresos,
        "saldo_inicial":         saldo_inicial,
        "saldo_final":           saldo_final,
        "no_hay_caja":           False,
    })

def historial_cierres(request, ruta_id):
    ruta      = get_object_or_404(Ruta, id=ruta_id)
    historial = ReporteDiario.objects.filter(ruta=ruta).order_by('-fecha')

    for registro in historial:
        registro.movimientos_del_dia = MovimientoRuta.objects.filter(
            ruta=ruta, fecha__date=registro.fecha
        ).order_by('fecha')

    return render(request, 'app/historial_cierres.html', {
        'ruta': ruta,
        'historial': historial
    })

# ================================================================================================================================================
# MAPA
# ================================================================================================================================================

def mapa_clientes(request, ruta_id):
    ruta     = get_object_or_404(Ruta, id=ruta_id)
    clientes = Targeta.objects.filter(ruta=ruta).exclude(latitud=None).exclude(longitud=None)

    return render(request, 'app/mapa_clientes.html', {
        'ruta': ruta,
        'clientes': clientes
    })

def reporte_rango(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if ruta.supervisor != request.user:
        return redirect('dashboard')

    fecha_inicio_str = request.GET.get('fecha_inicio')
    fecha_fin_str    = request.GET.get('fecha_fin')

    if not fecha_inicio_str or not fecha_fin_str:
        return render(request, 'app/reporte_rango.html', {
            'ruta': ruta,
            'fecha_inicio': None,
            'fecha_fin': None,
        })

    try:
        fecha_inicio = datetime.datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
        fecha_fin    = datetime.datetime.strptime(fecha_fin_str,    "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return redirect('dashboard')

    inicio_dia = make_aware(datetime.datetime.combine(fecha_inicio, datetime.time.min))
    fin_dia    = make_aware(datetime.datetime.combine(fecha_fin,    datetime.time.max))

    # ── Ingresos: abonos ───────────────────────────────────────────────────────
    total_abonos = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__range=(inicio_dia, fin_dia)
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    # ── Capital ingresado en el rango ──────────────────────────────────────────
    total_capital_rango = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='INGRESO',
        descripcion__startswith='CAPITAL:',
        fecha__range=(inicio_dia, fin_dia)
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    # ── Egresos desglosados ─────────────────────────────────────────────────────
    total_prestamos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        descripcion__startswith='Préstamo otorgado',
        fecha__range=(inicio_dia, fin_dia)
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    total_renovaciones = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        descripcion__startswith='RENOVACIÓN',
        fecha__range=(inicio_dia, fin_dia)
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    total_gastos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        descripcion__startswith='GASTO:',
        fecha__range=(inicio_dia, fin_dia)
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    total_otros = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo='EGRESO',
        fecha__range=(inicio_dia, fin_dia)
    ).exclude(
        descripcion__startswith='Préstamo otorgado'
    ).exclude(
        descripcion__startswith='RENOVACIÓN'
    ).exclude(
        descripcion__startswith='GASTO:'
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    total_egresos = total_prestamos + total_renovaciones + total_gastos + total_otros
    neto = total_abonos + total_capital_rango - total_egresos

    # ── Desglose por día ────────────────────────────────────────────────────────
    abonos_por_dia_agg = {
        a['fecha__date']: a['total']
        for a in Abono.objects
            .filter(targeta__ruta=ruta, fecha__range=(inicio_dia, fin_dia))
            .values('fecha__date')
            .annotate(total=Sum('monto'))
    }
    egresos_por_dia_agg = {
        e['fecha__date']: e['total']
        for e in MovimientoRuta.objects
            .filter(ruta=ruta, tipo='EGRESO', fecha__range=(inicio_dia, fin_dia))
            .values('fecha__date')
            .annotate(total=Sum('monto'))
    }
    capital_por_dia_agg = {
        c['fecha__date']: c['total']
        for c in MovimientoRuta.objects
            .filter(ruta=ruta, tipo='INGRESO', descripcion__startswith='CAPITAL:', fecha__range=(inicio_dia, fin_dia))
            .values('fecha__date')
            .annotate(total=Sum('monto'))
    }
    dias_con_actividad = sorted(
        set(
            list(abonos_por_dia_agg.keys()) +
            list(egresos_por_dia_agg.keys()) +
            list(capital_por_dia_agg.keys())
        ),
        reverse=True
    )

    dias = []
    for dia in dias_con_actividad:
        abonos_qs = (
            Abono.objects
                .filter(targeta__ruta=ruta, fecha__date=dia)
                .select_related('targeta', 'registrado_por')
                .order_by('fecha')
        )
        abonos = [
            {
                'cliente': a.targeta.nombre_cliente,
                'monto':   a.monto,
                'hora':    a.fecha,
                'usuario': a.registrado_por.username if a.registrado_por else None,
            }
            for a in abonos_qs
        ]
        total_abonos_dia = sum(a['monto'] for a in abonos)

        # Capital del día
        capital_qs = MovimientoRuta.objects.filter(
            ruta=ruta,
            tipo='INGRESO',
            descripcion__startswith='CAPITAL:',
            fecha__date=dia
        ).order_by('fecha')
        capital_list = [
            {
                'descripcion': mov.descripcion.replace('CAPITAL:', '').strip(),
                'monto':       mov.monto,
                'hora':        mov.fecha,
            }
            for mov in capital_qs
        ]
        total_capital_dia = sum(m['monto'] for m in capital_list)

        prestamos    = []
        renovaciones = []
        gastos       = []

        for mov in MovimientoRuta.objects.filter(ruta=ruta, tipo='EGRESO', fecha__date=dia).order_by('fecha'):
            desc = mov.descripcion or ''
            base = {
                'monto':   mov.monto,
                'hora':    mov.fecha,
                'usuario': None,
            }
            if desc.startswith('Préstamo otorgado'):
                prestamos.append({**base, 'cliente': desc.replace('Préstamo otorgado a ', '').strip()})
            elif 'RENOVACIÓN' in desc:
                renovaciones.append({**base, 'cliente': desc.replace('RENOVACIÓN (Restauración):', '').strip()})
            elif desc.startswith('GASTO:'):
                gastos.append({**base, 'descripcion': desc.replace('GASTO:', '').strip()})
            else:
                gastos.append({**base, 'descripcion': desc})

        total_prestamos_dia   = sum(m['monto'] for m in prestamos)
        total_renovaciones_dia = sum(m['monto'] for m in renovaciones)
        total_gastos_dia      = sum(m['monto'] for m in gastos)
        total_egresos_dia     = total_prestamos_dia + total_renovaciones_dia + total_gastos_dia

        dias.append({
            'fecha': dia,
            'ingresos': total_abonos_dia + total_capital_dia,
            'egresos': total_egresos_dia,
            'neto': total_abonos_dia + total_capital_dia - total_egresos_dia,
            'total_movimientos': len(abonos) + len(capital_list) + len(prestamos) + len(renovaciones) + len(gastos),
            'abonos': abonos,
            'capital': capital_list,
            'prestamos': prestamos,
            'renovaciones': renovaciones,
            'gastos': gastos,
            'total_abonos': total_abonos_dia,
            'total_capital_dia': total_capital_dia,
            'total_prestamos': total_prestamos_dia,
            'total_renovaciones': total_renovaciones_dia,
            'total_gastos': total_gastos_dia,
        })

    return render(request, 'app/reporte_rango.html', {
        'ruta': ruta,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'total_abonos': total_abonos,
        'total_capital_rango': total_capital_rango,
        'total_prestamos': total_prestamos,
        'total_renovaciones': total_renovaciones,
        'total_gastos': total_gastos,
        'total_otros': total_otros,
        'total_egresos': total_egresos,
        'neto': neto,
        'dias': dias,
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








































































import json
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

import json
from groq import Groq
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

import json
from groq import Groq
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

# ================================================================================
# REEMPLAZA la función asistente_chat en tu views.py con esta versión completa.
# El único cambio está en el sistema_prompt — todo lo demás queda igual.
# ================================================================================

@login_required
@require_POST
def asistente_chat(request):
    """
    Vista para el asistente virtual 'PrestAyuda' integrado en PrestApp.
    Utiliza Groq Cloud (Llama 3.3) para ofrecer respuestas humanas, cálidas
    y basadas exactamente en la interfaz que ve el usuario.
    """
    try:
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            return JsonResponse({"error": "La API Key de Groq no está configurada"}, status=500)

        client = Groq(api_key=api_key)

        data = json.loads(request.body)
        mensaje_usuario = data.get("mensaje", "")

        if not mensaje_usuario:
            return JsonResponse({"error": "Mensaje vacío"}, status=400)

        sistema_prompt = """
Eres **PrestAyuda**, el asistente integrado en **PrestApp**, una aplicación de gestión de préstamos a domicilio (gota a gota / diario).
Tu tono es el de un compañero de trabajo experimentado: directo, cálido, sin rodeos, como si estuvieras al lado del cobrador en la calle.
Nunca uses preámbulos largos. Responde siempre con viñetas cortas, negritas donde ayuden, y termina con una línea **💡 Consejo rápido:** motivador y práctico.

════════════════════════════════════════════════
🏗️  ESTRUCTURA GENERAL DE LA APP
════════════════════════════════════════════════
PrestApp tiene 3 roles:
• **ADMIN** → ve todas las rutas y usuarios.
• **SUPERVISOR** → gestiona sus propias rutas: crea/edita/renueva tarjetas, ve reportes, maneja caja.
• **TRABAJADOR** → solo cobra y registra gastos en las rutas que le asignaron.

Al iniciar sesión el sistema detecta el rol y redirige al panel correcto automáticamente.

════════════════════════════════════════════════
📍  PANEL PRINCIPAL (supervisor.html / trabajador.html)
════════════════════════════════════════════════
• **Barra de rutas** (arriba): botones con el nombre de cada zona. Hay que TOCAR la ruta para ver sus clientes. Si la pantalla sale vacía, es porque no se eligió ruta.
• **Botón "⚡ Acciones de ruta"**: menú desplegable con todas las acciones disponibles para la ruta seleccionada (solo aparece cuando hay una ruta activa).
• **Tarjetas de clientes**: cada tarjeta muestra nombre, identificación, saldo, progreso de cuotas y teléfono.
  - Tarjeta con **franja verde** = ya pagó hoy ✅
  - Tarjeta con **franja roja** = cobro atrasado según su frecuencia ⚠️
  - Sin color especial = al día pero sin pago hoy todavía.
• **Botón 💵 Abonar** (en la tarjeta): abre el formulario para registrar el pago del cliente.
• **Menú ⋮** (tres puntos): despliega opciones secundarias de esa tarjeta:
  - 🕒 Historial → ver todos los abonos que ha hecho ese cliente.
  - 📝 Editar → corregir datos del cliente o del préstamo.
  - 🔄 Renovar → darle un préstamo nuevo sin borrar el historial.
  - 🗑️ Eliminar → borrar la tarjeta (pide confirmación y registra la pérdida en caja).
• **Resumen de la ruta** (tres recuadros): muestra total de clientes activos, Base disponible (dinero en caja) y dinero En Ruta (saldo pendiente por cobrar).
• **Buscador 🔍**: filtrar clientes por nombre en tiempo real.

════════════════════════════════════════════════
💵  REGISTRAR UN ABONO
════════════════════════════════════════════════
1. Ubicar la tarjeta del cliente en el panel.
2. Tocar **💵 Abonar**.
3. Ingresar el monto y confirmar.
**Cómo funciona por dentro:**
- El abono se aplica en cascada: primero paga la cuota más vieja, luego la siguiente, y así.
- Si el saldo llega a $0, la tarjeta cambia sola a estado "Pagada" y desaparece del panel.
- El dinero entra automáticamente a la base (caja) de la ruta.
- La cuota queda marcada como PAGADA con fecha y hora exactas.
Frecuencias de cobro:
- DIARIO → se marca atrasado si lleva más de 1 día sin pagar.
- SEMANAL → más de 7 días.
- QUINCENAL → más de 15 días.
- MENSUAL → más de 30 días.

════════════════════════════════════════════════
➕  CREAR UNA NUEVA TARJETA (PRÉSTAMO)
════════════════════════════════════════════════
1. Seleccionar la ruta.
2. Tocar **⚡ Acciones de ruta → ➕ Nueva targeta**.
3. Llenar: tipo y número de identificación, nombre, teléfono, dirección (opcional), monto, tasa de interés (%), plazo en días y frecuencia de cobro.
**Qué hace el sistema:**
- Resta el monto de la Base de la ruta (si no hay saldo suficiente, bloquea la creación).
- Genera automáticamente todas las cuotas con fechas de vencimiento.
- Registra un EGRESO en la caja de la ruta.
- La tarjeta aparece en el panel del supervisor y del trabajador asignado.

════════════════════════════════════════════════
🔄  RENOVAR UNA TARJETA (CLIENTE ACTIVO)
════════════════════════════════════════════════
1. Abrir el menú ⋮ de la tarjeta del cliente.
2. Tocar **🔄 Renovar**.
3. Ingresar el nuevo monto, tasa y plazo.
**Importante:**
- El historial de pagos anteriores NO se borra (quedan en base de datos).
- Se crea un nuevo ciclo de cuotas desde cero.
- El monto nuevo se descuenta de la base de la ruta.
- Se registra un EGRESO de "RENOVACIÓN" en la caja.
- Usar cuando el cliente terminó su ciclo y quiere un préstamo nuevo, o cuando se quiere ajustar condiciones.

════════════════════════════════════════════════
💰  INGRESO DE CAPITAL (Recarga de caja)
════════════════════════════════════════════════
1. Tocar **⚡ Acciones de ruta → 💰 Ingreso de capital**.
2. Ingresar el monto que se está metiendo a la ruta.
- Suma directamente a la Base de la ruta.
- Queda registrado como INGRESO en el historial de movimientos.
- Usar cuando el supervisor inyecta dinero fresco para dar más préstamos.

════════════════════════════════════════════════
💸  REGISTRAR UN GASTO
════════════════════════════════════════════════
1. Tocar **⚡ Acciones de ruta → 💸 Registrar gasto**.
2. Ingresar el monto y una descripción del gasto.
- Resta de la Base de la ruta automáticamente.
- Queda registrado como EGRESO con prefijo "GASTO:" en el historial.
- Ejemplos: gasolina, refrigerio del cobrador, papelería, imprevistos.

════════════════════════════════════════════════
📊  REPORTE DIARIO
════════════════════════════════════════════════
1. Tocar **⚡ Acciones de ruta → 📊 Reporte diario**.
- Muestra todos los abonos cobrados hoy, préstamos entregados, gastos y renovaciones del día.
- Da totales de ingresos, egresos y neto del día.
- Útil para hacer el cierre del día y verificar que la caja cuadre.

════════════════════════════════════════════════
📅  REPORTE POR RANGO
════════════════════════════════════════════════
1. Tocar **⚡ Acciones de ruta → 📅 Reporte por rango**.
2. Seleccionar fecha de inicio y fecha final.
- Muestra día a día: abonos, préstamos, renovaciones, gastos y neto.
- Ideal para rendir cuentas semanales o mensuales.

════════════════════════════════════════════════
💰  HISTORIAL DE CAJAS
════════════════════════════════════════════════
1. Tocar **⚡ Acciones de ruta → 💰 Historial cajas**.
- Muestra el registro de cierres de caja diarios con saldo inicial, ingresos, egresos y saldo final.
- Las cajas se cierran automáticamente cada día.

════════════════════════════════════════════════
📂  CLIENTES FINALIZADOS
════════════════════════════════════════════════
1. Tocar **⚡ Acciones de ruta → 📂 Ver finalizados**.
- Lista todos los clientes que ya pagaron su préstamo completo (estado PAGADA).
- Sirve para verificar historial o para renovar a un cliente que ya terminó.

════════════════════════════════════════════════
📍  MAPA DE RUTA (GPS)
════════════════════════════════════════════════
1. Tocar **⚡ Acciones de ruta → 📍 Ver mapa de ruta**.
- Muestra en Google Maps la ubicación de todos los clientes con GPS guardado.
- En cada tarjeta también aparece un enlace directo a la ubicación del cliente.
- Para guardar/actualizar la ubicación de un cliente: editar su tarjeta → opción "Validar GPS" o se captura automáticamente desde el celular al registrar el cliente.

════════════════════════════════════════════════
🕒  HISTORIAL DE ABONOS DE UN CLIENTE
════════════════════════════════════════════════
1. En la tarjeta del cliente → menú ⋮ → **🕒 Historial**.
- Muestra todos los abonos registrados: fecha, hora, monto y quién lo registró.
- Útil para resolver disputas o verificar pagos con el cliente.

════════════════════════════════════════════════
📝  EDITAR UNA TARJETA
════════════════════════════════════════════════
1. En la tarjeta del cliente → menú ⋮ → **📝 Editar**.
- Permite corregir: datos personales, teléfono, dirección, tasa, plazo, monto base y frecuencia.
- Solo el SUPERVISOR puede editar tarjetas.

════════════════════════════════════════════════
🗑️  ELIMINAR UNA TARJETA
════════════════════════════════════════════════
1. En la tarjeta del cliente → menú ⋮ → **🗑️ Eliminar**.
- El sistema pide confirmación antes de borrar.
- Si el cliente tiene saldo pendiente, se registra automáticamente un EGRESO por la pérdida.
- Esta acción es irreversible. Solo para casos de pérdida real o error grave.

════════════════════════════════════════════════
📐  LÓGICA FINANCIERA (para cálculos y dudas)
════════════════════════════════════════════════
• **Monto total** = monto_base + (monto_base × tasa%) → ej: $100.000 al 20% = $120.000
• **Cuota** = monto_total ÷ número de cuotas según plazo y frecuencia
• **Saldo restante** = monto_total − total_abonado_en_ciclo_actual
• **Base** = dinero disponible en la caja de la ruta para dar préstamos
• **En Ruta** = suma de saldos pendientes de todos los clientes activos
• Los abonos anteriores a una renovación no se borran, quedan con un "offset" que el sistema descuenta automáticamente del cálculo del ciclo nuevo.

════════════════════════════════════════════════
🔐  ROLES Y PERMISOS
════════════════════════════════════════════════
• SUPERVISOR: puede crear/editar/renovar/eliminar tarjetas, ver reportes, manejar caja, ver mapa.
• TRABAJADOR: solo puede registrar abonos y gastos. NO puede crear ni eliminar tarjetas.
• ADMIN: gestión de rutas y usuarios del sistema completo.

════════════════════════════════════════════════
⚡  PROBLEMAS FRECUENTES Y SOLUCIONES
════════════════════════════════════════════════
• "No veo clientes" → Debes seleccionar una ruta en los botones de arriba.
• "No puedo crear tarjeta" → La base de la ruta no tiene saldo suficiente. Usa "Ingreso de capital".
• "El cliente pagó pero sigue en rojo" → Refresca la página. El estado se actualiza en tiempo real.
• "Quiero dar un préstamo nuevo al mismo cliente sin borrar su historial" → Usa "🔄 Renovar".
• "La tarjeta desapareció del panel" → El cliente terminó de pagar. Está en "📂 Ver finalizados".
• "No aparece el botón Acciones de ruta" → Primero debes seleccionar una ruta tocando su botón arriba.
"""

        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": sistema_prompt},
                {"role": "user", "content": mensaje_usuario}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.65,
        )

        respuesta_ia = chat_completion.choices[0].message.content
        return JsonResponse({"respuesta": respuesta_ia})

    except Exception as e:
        print(f"❌ ERROR REAL EN PRESTAYUDA: {str(e)}")
        return JsonResponse({"error": f"Error real: {str(e)}"}, status=500)