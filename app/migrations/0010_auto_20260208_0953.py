from django.db import migrations

def create_superuser(apps, schema_editor):
    # Usamos apps.get_model para evitar problemas de importación circular
    User = apps.get_model('auth', 'User')
    if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser(
            username='admin',
            email='admin@gmail.com',
            password='admindjango12345*'  # <--- CAMBIA ESTO POR TU CLAVE
        )

class Migration(migrations.Migration):

    dependencies = [
        ('app', '0009_alter_abono_cuota'), # Esto asegura que se ejecute después de tus tablas
    ]

    operations = [
        migrations.RunPython(create_superuser),
    ]