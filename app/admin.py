from django.contrib import admin
from .models import Perfil, Ruta, Targeta, Abono
from django.contrib import admin
from .models import CajaRuta


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'rol')
    list_filter = ('rol',)


@admin.register(Ruta)
class RutaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'supervisor', 'activa')
    list_filter = ('activa',)
    filter_horizontal = ('trabajadores',)


class AbonoInline(admin.TabularInline):
    model = Abono
    extra = 0


@admin.register(Targeta)
class TargetaAdmin(admin.ModelAdmin):
    list_display = ('nombre_cliente', 'numero_identificacion', 'ruta', 'estado')
    list_filter = ('estado', 'ruta')
    search_fields = ('nombre_cliente', 'numero_identificacion')
    inlines = [AbonoInline]


@admin.register(Abono)
class AbonoAdmin(admin.ModelAdmin):
    list_display = ('targeta', 'monto', 'fecha')


from django.contrib import admin
from .models import CajaRuta

@admin.register(CajaRuta)
class CajaRutaAdmin(admin.ModelAdmin):
    list_display = (
        'ruta',
        'fecha',
        'cerrada',
        'saldo_inicial',
        'ingresos',
        'egresos',
        'saldo_final'
    )

    list_filter = ('ruta', 'cerrada', 'fecha')
    search_fields = ('ruta__nombre',)

