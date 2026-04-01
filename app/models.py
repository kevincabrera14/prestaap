from django.db import models
from django.contrib.auth.models import User
from django.db.models import Sum
from decimal import Decimal
from django.utils.timezone import localdate

# -------------------------
# PERFIL DE USUARIO (ROL)
# -------------------------
class Perfil(models.Model):
    ROL_CHOICES = (
        ('ADMIN', 'Administrador'),
        ('SUPERVISOR', 'Supervisor'),
        ('TRABAJADOR', 'Trabajador'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.CharField(max_length=15, choices=ROL_CHOICES)

    def __str__(self):
        return f"{self.user.username} - {self.rol}"


# -------------------------
# RUTA
# -------------------------
class Ruta(models.Model):
    nombre = models.CharField(max_length=100)

    supervisor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='rutas_supervisor'
    )

    trabajadores = models.ManyToManyField(
        User,
        related_name='rutas_trabajador',
        blank=True
    )

    base = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    activa = models.BooleanField(default=True)

    @property
    def dinero_en_ruta(self):
        return self.targetas.aggregate(
            total=Sum('monto_base')
        )['total'] or Decimal('0.00')

    def __str__(self):
        return self.nombre


# -------------------------
# TARGETA (PRÉSTAMO)
# -------------------------
class Targeta(models.Model):
    ESTADO_CHOICES = (
        ('PAGO', 'Al día'),
        ('MORA', 'En mora'),
        ('PAGADA', 'Finalizada/Pagada'),
    )

    ruta = models.ForeignKey(
        Ruta,
        on_delete=models.CASCADE,
        related_name='targetas'
    )

    # -------- INFO CLIENTE --------
    tipo_identificacion = models.CharField(max_length=20)
    numero_identificacion = models.CharField(max_length=30)
    nombre_cliente = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    direccion_casa = models.CharField(max_length=200)
    direccion_negocio = models.CharField(max_length=200, blank=True)
    observaciones = models.TextField(blank=True)

    # NUEVO: Geolocalización para el Mapa Visual
    latitud = models.FloatField(null=True, blank=True)
    longitud = models.FloatField(null=True, blank=True)

    # -------- INFO PRÉSTAMO --------
    monto_base = models.DecimalField(max_digits=10, decimal_places=2)
    tasa_interes = models.PositiveIntegerField()
    plazo_dias = models.PositiveIntegerField()
    fecha_creacion = models.DateField(auto_now_add=True)

    estado = models.CharField(
        max_length=10,
        choices=ESTADO_CHOICES,
        default='MORA'
    )

    creada_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )

    # ===============================
    #  MÉTODOS Y CÁLCULOS
    # ===============================

    @property
    def monto_total(self):
        interes = (self.monto_base * Decimal(self.tasa_interes)) / Decimal(100)
        return self.monto_base + interes

    @property
    def total_abonado(self):
        total = self.abonos.aggregate(
            total=Sum('monto')
        )['total']
        return total if total else Decimal('0.00')

    @property
    def saldo_restante(self):
        return self.monto_total - self.total_abonado

    def actualizar_estado(self):
        """Actualiza si la tarjeta está al día, en mora o pagada por completo."""
        hoy = localdate()
        saldo = self.saldo_restante

        # 1. Si el saldo es 0 o menos, el crédito terminó
        if saldo <= Decimal('0.00'):
            self.estado = 'PAGADA'
        
        # 2. Si es domingo, no penalizamos ni cambiamos el estado
        elif hoy.weekday() == 6:
            pass

        # 3. Revisar si hay cuotas vencidas (estado PENDIENTE y fecha < hoy)
        elif self.cuotas.filter(estado='PENDIENTE', fecha_vencimiento__lt=hoy).exists():
            self.estado = 'MORA'
        
        else:
            self.estado = 'PAGO'
            
        self.save(update_fields=['estado'])

    def __str__(self):
        return f"{self.nombre_cliente} - {self.numero_identificacion}"


# -------------------------
# CUOTAS
# -------------------------
class Cuota(models.Model):
    ESTADO_CHOICES = (
        ('PENDIENTE', 'Pendiente'),
        ('PAGADA', 'Pagada'),
    )

    targeta = models.ForeignKey(Targeta, on_delete=models.CASCADE, related_name='cuotas')
    fecha_vencimiento = models.DateField(null=True, blank=True)
    numero = models.PositiveIntegerField()
    monto = models.DecimalField(max_digits=10, decimal_places=2) 
    
    # Saldo específico de esta cuota
    saldo_cuota = models.DecimalField(max_digits=10, decimal_places=2, default=0) 

    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='PENDIENTE')
    fecha_pago = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['numero']
        unique_together = ('targeta', 'numero')

    def save(self, *args, **kwargs):
        if not self.pk:
            self.saldo_cuota = self.monto
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Cuota {self.numero} - {self.targeta.nombre_cliente} (Faltan: {self.saldo_cuota})"


# -------------------------
# ABONOS
# -------------------------
class Abono(models.Model):
    targeta = models.ForeignKey(
        Targeta,
        on_delete=models.CASCADE,
        related_name='abonos'
    )

    cuota = models.ForeignKey(
        Cuota,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateTimeField(auto_now_add=True)

    registrado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )

    def __str__(self):
        return f"Abono {self.id} - {self.targeta.nombre_cliente}"


# -------------------------
# CAJA Y MOVIMIENTOS
# -------------------------
class CajaRuta(models.Model):
    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE)
    fecha = models.DateField()

    saldo_inicial = models.DecimalField(max_digits=12, decimal_places=2)
    ingresos = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    egresos = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    saldo_final = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    cerrada = models.BooleanField(default=False)

    class Meta:
        unique_together = ("ruta", "fecha")
        ordering = ["-fecha"]

    def __str__(self):
        return f"Caja {self.ruta} - {self.fecha}"


class MovimientoRuta(models.Model):
    TIPO_CHOICES = (
        ('INGRESO', 'Ingreso'),
        ('EGRESO', 'Egreso'),
    )

    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE, related_name='movimientos')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateTimeField(auto_now_add=True)
    descripcion = models.TextField(blank=True)

    def __str__(self):
        return f"{self.fecha.date()} - {self.tipo} - {self.monto}"