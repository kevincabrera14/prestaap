from django.core.management.base import BaseCommand
from django.utils.timezone import localdate, datetime, time, make_aware
from app.models import Ruta, CajaRuta, Abono, MovimientoRuta
from decimal import Decimal
from django.db.models import Sum

class Command(BaseCommand):
    help = 'Procesa y cierra todas las cajas pendientes del pasado y abre la de hoy'

    def handle(self, *args, **options):
        hoy = localdate()
        rutas = Ruta.objects.all()
        
        for ruta in rutas:
            # 1. CERRAR TODO LO PENDIENTE (Ayer y días anteriores olvidados)
            cajas_pendientes = CajaRuta.objects.filter(ruta=ruta, fecha__lt=hoy, cerrada=False)
            
            for caja in cajas_pendientes:
                # Rango de tiempo exacto para el día de ESA caja
                inicio = make_aware(datetime.combine(caja.fecha, time.min))
                fin = make_aware(datetime.combine(caja.fecha, time.max))
                
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
                
                # Actualizar la base real de la ruta para el siguiente día
                ruta.base = caja.saldo_final
                ruta.save()
                self.stdout.write(self.style.SUCCESS(f"✅ Cerrada caja pendiente: {ruta.nombre} - {caja.fecha}"))

            # 2. ASEGURAR QUE LA CAJA DE HOY EXISTA
            caja_hoy, created = CajaRuta.objects.get_or_create(
                ruta=ruta,
                fecha=hoy,
                defaults={'saldo_inicial': ruta.base, 'cerrada': False}
            )
            if created:
                self.stdout.write(f"ℹ️ Caja de hoy iniciada para {ruta.nombre}")

        self.stdout.write(self.style.SUCCESS('--- Proceso finalizado ---'))