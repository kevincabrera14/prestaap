from django.core.management.base import BaseCommand
from django.utils.timezone import localdate, timedelta, datetime, time, make_aware
from app.models import Ruta, CajaRuta, Abono, MovimientoRuta
from decimal import Decimal
from django.db.models import Sum

class Command(BaseCommand):
    help = 'Cierra la caja del día anterior y abre la del nuevo día para todas las rutas'

    def handle(self, *args, **options):
        hoy = localdate()
        ayer = hoy - timedelta(days=1)
        
        rutas = Ruta.objects.all()
        
        for ruta in rutas:
            # 1. PROCESAR Y CERRAR CAJA DE AYER
            caja_ayer, created = CajaRuta.objects.get_or_create(
                ruta=ruta,
                fecha=ayer,
                defaults={'saldo_inicial': ruta.base}
            )
            
            if not caja_ayer.cerrada:
                # Calcular montos exactos de ayer
                inicio = make_aware(datetime.combine(ayer, time.min))
                fin = make_aware(datetime.combine(ayer, time.max))
                
                ingresos = Abono.objects.filter(
                    targeta__ruta=ruta, 
                    fecha__range=(inicio, fin)
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
                
                egresos = MovimientoRuta.objects.filter(
                    ruta=ruta, 
                    tipo='EGRESO', 
                    fecha__range=(inicio, fin)
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
                
                caja_ayer.ingresos = ingresos
                caja_ayer.egresos = egresos
                caja_ayer.saldo_final = caja_ayer.saldo_inicial + ingresos - egresos
                caja_ayer.cerrada = True
                caja_ayer.save()
                
                # Actualizar la base real de la ruta con el cierre
                ruta.base = caja_ayer.saldo_final
                ruta.save()
                self.stdout.write(f"Caja cerrada para {ruta.nombre} - Fecha: {ayer}")

            # 2. REABRIR / CREAR CAJA DE HOY INSTANTÁNEAMENTE
            caja_hoy, created_hoy = CajaRuta.objects.get_or_create(
                ruta=ruta,
                fecha=hoy,
                defaults={'saldo_inicial': ruta.base, 'cerrada': False}
            )
            if created_hoy:
                self.stdout.write(f"Nueva caja abierta para {ruta.nombre} - Fecha: {hoy}")

        self.stdout.write(self.style.SUCCESS('Proceso de cierre y apertura completado.'))