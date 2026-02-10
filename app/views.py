#views 
# =====================================================
# import
# =====================================================
from django.utils.timezone import localtime, make_aware, get_current_timezone, localdate
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .permissions import supervisor_required
from .models import Ruta, Targeta, Abono, MovimientoRuta,CajaRuta,Cuota
from django.contrib import messages
from django.db.models import Sum
from decimal import Decimal
from datetime import *
from datetime import datetime, date, time
from django.utils import timezone


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


def dashboard_supervisor(request):
    rutas = Ruta.objects.all()
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
        ruta_sel = get_object_or_404(Ruta, id=ruta_id)

        targetas = Targeta.objects.filter(ruta=ruta_sel)

        if q:
            targetas = targetas.filter(nombre_cliente__icontains=q)

        # =========================
        # RESUMEN FINANCIERO REAL
        # =========================

        resumen["total_clientes"] = targetas.count()

        resumen["en_mora"] = targetas.filter(
            estado="MORA"
        ).count()

        resumen["base"] = ruta_sel.base

        resumen["dinero_en_ruta"] = sum(
            t.saldo_restante for t in targetas
        )

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
    targeta = get_object_or_404(Targeta, id=targeta_id, ruta__supervisor=request.user)
    targeta.delete()
    messages.success(request, "Targeta eliminada")
    return redirect('dashboard_supervisor')


# =====================================================
# TRABAJADOR
# =====================================================

@login_required
def dashboard_trabajador(request):
    rutas = Ruta.objects.filter(trabajadores=request.user)
    targetas = Targeta.objects.filter(ruta__in=rutas)

    q = request.GET.get("q")
    estado = request.GET.get("estado")
    ruta_id = request.GET.get("ruta")

    if q:
        targetas = targetas.filter(nombre_cliente__icontains=q)
    if estado:
        targetas = targetas.filter(estado=estado)
    if ruta_id:
        targetas = targetas.filter(ruta_id=ruta_id)

    resumen = {
        "total_clientes": targetas.count(),
        "en_mora": targetas.filter(estado="MORA").count(),
        "total_saldo": sum(t.saldo_restante for t in targetas),
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


from django.utils.timezone import now
@login_required
def crear_abono(request, targeta_id):
    targeta = get_object_or_404(Targeta, id=targeta_id)
    ruta = targeta.ruta
    hoy = localdate()

    cuotas = targeta.cuotas.filter(estado='PENDIENTE')

    if request.method == "POST":
        cuota_id = request.POST.get("cuota")
        cuota = get_object_or_404(Cuota, id=cuota_id, estado='PENDIENTE')

        # 1️⃣ Marcar cuota
        cuota.estado = 'PAGADA'
        cuota.fecha_pago = now()
        cuota.save()

        # 2️⃣ Abono
        Abono.objects.create(
            targeta=targeta,
            cuota=cuota,
            monto=cuota.monto,
            registrado_por=request.user
        )

        # 3️⃣ Base
        ruta.base += cuota.monto
        ruta.save(update_fields=['base'])

        # 4️⃣ Movimiento
        MovimientoRuta.objects.create(
            ruta=ruta,
            tipo='INGRESO',
            monto=cuota.monto,
            descripcion=f"Pago cuota {cuota.numero} - {targeta.nombre_cliente}"
        )

        targeta.actualizar_estado()
        messages.success(request, "Cuota pagada correctamente")

        # =====================================================
        # REDIRECCIÓN CORREGIDA SEGÚN TU URLCONF
        # =====================================================
        try:
            rol = request.user.perfil.rol
        except:
            rol = 'TRABAJADOR' 

        if rol == 'SUPERVISOR' or request.user.is_staff:
            return redirect(f"/dashboard/supervisor/?ruta={ruta.id}")
        else:
            return redirect(f"/dashboard/trabajador/?ruta={ruta.id}")

    return render(request, "app/crear_abono.html", {
        "targeta": targeta,
        "cuotas": cuotas
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


@login_required
def historial_cajas(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)
    
    # Esto asegura que si el cron no ha corrido, se intenten cerrar las viejas al entrar
    from django.core.management import call_command
    try:
        call_command('cerrar_cajas')
    except:
        pass

    historial = CajaRuta.objects.filter(ruta=ruta, cerrada=True).order_by('-fecha')
    
    return render(request, "app/historial_cajas.html", {
        "ruta": ruta,
        "historial": historial
    })

# =====================================================
# 🔒 CIERRE AUTOMÁTICO DE CAJAS ANTERIORES
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
    try:
        cerrar_cajas_anteriores(ruta)
    except Exception:
        pass  # evita que una caja vieja rompa todo

    # ===============================
    # 📦 CAJA DEL DÍA
    # ===============================
    ultima_caja = CajaRuta.objects.filter(
        ruta=ruta,
        cerrada=True
    ).exclude(saldo_final__isnull=True).order_by("-fecha").first()

    saldo_inicial = ultima_caja.saldo_final if ultima_caja else ruta.base

    caja, _ = CajaRuta.objects.get_or_create(
        ruta=ruta,
        fecha=hoy,
        defaults={"saldo_inicial": saldo_inicial}
    )

    # ===============================
    # 📥 INGRESOS (SIN fecha__date)
    # ===============================
    abonos = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__gte=hoy,
        fecha__lt=hoy + timedelta(days=1)
    )

    ingresos_hoy = abonos.aggregate(
        total=Sum("monto")
    )["total"] or Decimal("0.00")

    # ===============================
    # 📤 EGRESOS (SIN fecha__date)
    # ===============================
    egresos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo="EGRESO",
        fecha__gte=hoy,
        fecha__lt=hoy + timedelta(days=1)
    )

    egresos_hoy = egresos.aggregate(
        total=Sum("monto")
    )["total"] or Decimal("0.00")

    # ===============================
    # 💾 ACTUALIZAR CAJA
    # ===============================
    caja.ingresos = ingresos_hoy
    caja.egresos = egresos_hoy
    caja.save()

    saldo_hoy = caja.saldo_inicial + ingresos_hoy - egresos_hoy

    # ===============================
    # 🧾 MOVIMIENTOS
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

    # 1. Convertir fecha y crear rango (Inicio y fin del día)
    try:
        fecha_reporte = datetime.strptime(fecha, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return redirect("dashboard_supervisor")

    # Definimos el inicio y fin del día para el filtro
    inicio_dia = timezone.make_aware(datetime.combine(fecha_reporte, time.min))
    fin_dia = timezone.make_aware(datetime.combine(fecha_reporte, time.max))
    hoy = date.today()

    # 2. Obtener o crear Caja
    caja, created = CajaRuta.objects.get_or_create(
        ruta=ruta, 
        fecha=fecha_reporte,
        defaults={'saldo_inicial': ruta.base, 'cerrada': False}
    )

    # 3. Consultar Abonos y Egresos usando RANGO (Evita el OperationalError)
    abonos = Abono.objects.filter(
        targeta__ruta=ruta,
        fecha__range=(inicio_dia, fin_dia)
    ).order_by("fecha")

    egresos = MovimientoRuta.objects.filter(
        ruta=ruta,
        tipo="EGRESO",
        fecha__range=(inicio_dia, fin_dia)
    ).order_by("fecha")

    # 4. Cálculos
    total_ingresos = abonos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")
    total_egresos = egresos.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    # 5. Guardado automático (Lógica de historial)
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

@login_required
def agregar_abono(request):
    targetas = Targeta.objects.all()
    cuotas = []

    targeta_id = request.GET.get("targeta")

    if targeta_id:
        cuotas = Cuota.objects.filter(
            targeta_id=targeta_id,
            estado='PENDIENTE'
        )

    if request.method == "POST":
        targeta_id = request.POST.get("targeta")
        cuota_id = request.POST.get("cuota")
        monto = request.POST.get("monto")

        targeta = get_object_or_404(Targeta, id=targeta_id)
        cuota = get_object_or_404(Cuota, id=cuota_id)

        Abono.objects.create(
            targeta=targeta,
            cuota=cuota,
            monto=Decimal(monto),
            registrado_por=request.user
        )

        # Marcar cuota como pagada
        cuota.estado = 'PAGADA'
        cuota.save(update_fields=['estado'])

        # Actualizar estado de la targeta
        targeta.actualizar_estado()

        messages.success(request, "Abono registrado correctamente")
        return redirect("agregar_abono")

    return render(request, "app/agregar_abono.html", {
        "targetas": targetas,
        "cuotas": cuotas,
        "targeta_id": targeta_id
    })



def crear_cuotas(targeta):
    monto_total = targeta.monto_total
    plazo = targeta.plazo_dias

    monto_cuota = (monto_total / Decimal(plazo)).quantize(Decimal('0.01'))

    for i in range(1, plazo + 1):
        Cuota.objects.create(
            targeta=targeta,
            numero=i,
            monto=monto_cuota
        )
