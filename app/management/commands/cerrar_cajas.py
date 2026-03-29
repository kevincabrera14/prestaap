from django.core.management.base import BaseCommand
from django.utils.timezone import now, localdate, make_aware
from app.models import Ruta, CajaRuta, Abono, MovimientoRuta
from decimal import Decimal
from django.db.models import Sum
import datetime

class Command(BaseCommand):
    help = 'Procesa y cierra todas las cajas pendientes del pasado y abre la de hoy'

    def handle(self, *args, **options):
        hoy = localdate()
        rutas = Ruta.objects.all()
        
        for ruta in rutas:
            # 1. CERRAR TODO LO PENDIENTE (Ordenado por fecha para no saltar saldos)
            cajas_pendientes = CajaRuta.objects.filter(
                ruta=ruta, 
                fecha__lt=hoy, 
                cerrada=False
            ).order_by('fecha')
            
            for caja in cajas_pendientes:
                inicio = make_aware(datetime.datetime.combine(caja.fecha, datetime.time.min))
                fin = make_aware(datetime.datetime.combine(caja.fecha, datetime.time.max))
                
                ingresos = Abono.objects.filter(
                    targeta__ruta=ruta, 
                    fecha__range=(inicio, fin)
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
                
                egresos = MovimientoRuta.objects.filter(
                    ruta=ruta, 
                    tipo='EGRESO', 
                    fecha__range=(inicio, fin)
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
                
                caja.ingresos = ingresos
                caja.egresos = egresos
                caja.saldo_final = caja.saldo_inicial + ingresos - egresos
                caja.cerrada = True
                caja.save()
                
                # 🔥 CORRECCIÓN CRÍTICA:
                # Solo actualizamos la base de la ruta si es el cierre que conecta con hoy.
                # Si cerramos una caja de hace 3 días, no tocamos la base actual, 
                # solo lo hacemos si es el cierre necesario para abrir la caja de hoy.
                if not CajaRuta.objects.filter(ruta=ruta, fecha=hoy).exists():
                    ruta.base = caja.saldo_final
                    ruta.save(update_fields=['base'])
                
                self.stdout.write(self.style.SUCCESS(f"✅ Cerrada caja: {ruta.nombre} - {caja.fecha}"))

            # 2. ASEGURAR QUE LA CAJA DE HOY EXISTA
            # Si la caja de hoy no existe, se crea con la base actual (que acabamos de actualizar arriba)
            caja_hoy, created = CajaRuta.objects.get_or_create(
                ruta=ruta,
                fecha=hoy,
                defaults={
                    'saldo_inicial': ruta.base, 
                    'cerrada': False,
                    'ingresos': 0,
                    'egresos': 0
                }
            )
            
            if created:
                self.stdout.write(f"ℹ️ Caja de hoy iniciada para {ruta.nombre} con base ${ruta.base}")

        self.stdout.write(self.style.SUCCESS('--- Proceso finalizado ---'))