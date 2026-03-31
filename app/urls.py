from django.urls import path
from . import views

urlpatterns = [
# =====================================================
# crud
# =====================================================
    path('', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard/supervisor/', views.dashboard_supervisor, name='dashboard_supervisor'),
    path('dashboard/trabajador/', views.dashboard_trabajador, name='dashboard_trabajador'),
    path('logout/', views.cerrar_sesion, name='logout'),

# =====================================================
# crud targetas
# =====================================================
    path('rutas/crear/', views.crear_ruta, name='crear_ruta'),
    path('rutas/editar/<int:ruta_id>/', views.editar_ruta, name='editar_ruta'),
    path('rutas/eliminar/<int:ruta_id>/', views.eliminar_ruta, name='eliminar_ruta'),
    path('targetas/crear/', views.crear_targeta, name='crear_targeta'),
    path('targetas/editar/<int:targeta_id>/', views.editar_targeta, name='editar_targeta'),
    path('targetas/eliminar/<int:targeta_id>/', views.eliminar_targeta, name='eliminar_targeta'),
    path('targetas/<int:targeta_id>/abonar/', views.crear_abono, name='crear_abono'),

# =====================================================
# detalles del sistema 
# =====================================================
    path('targetas/<int:targeta_id>/historial/', views.historial_abonos, name='historial_abonos'),
    path('ruta/<int:ruta_id>/movimientos/', views.movimientos_ruta, name='movimientos_ruta'),
    path('ruta/<int:ruta_id>/retiro/', views.retiro_justificado, name='retiro_justificado'),
    path('ruta/<int:ruta_id>/cajas/', views.historial_cajas, name='historial_cajas'),
   
    path('reporte-diario/<int:ruta_id>/<str:fecha>/',views.reporte_diario,name='reporte_diario'),
    
    path('ruta/<int:ruta_id>/cajas/', views.historial_cajas, name='historial_cajas'),
    
    # AGREGA ESTA LÍNEA AQUÍ:
    path('ruta/<int:ruta_id>/gasto/', views.registrar_gasto, name='registrar_gasto'),

    path('reporte-diario/<int:ruta_id>/<str:fecha>/', views.reporte_diario, name='reporte_diario'),


    path('targetas/abonar/', views.crear_abono, name='crear_abono'),
    path('targetas/<int:targeta_id>/abonar/', views.crear_abono, name='crear_abono_especifico'),
]
