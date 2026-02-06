from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
from functools import wraps
from django.utils.timezone import localdate
from .models import CajaRuta


def _sin_permiso(request):
    messages.error(request, "No tienes permiso para acceder aquí")
    return redirect('dashboard')


# -------------------------
# ADMIN
# -------------------------
def solo_admin(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            if request.user.perfil.rol != 'ADMIN':
                return _sin_permiso(request)
        except:
            logout(request)
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


# -------------------------
# SUPERVISOR
# -------------------------
def supervisor_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            if request.user.perfil.rol != 'SUPERVISOR':
                return _sin_permiso(request)
        except:
            logout(request)
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


# -------------------------
# TRABAJADOR
# -------------------------
def solo_trabajador(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            if request.user.perfil.rol != 'TRABAJADOR':
                return _sin_permiso(request)
        except:
            logout(request)
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper




