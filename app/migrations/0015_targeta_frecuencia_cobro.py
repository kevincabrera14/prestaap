from django.db import migrations, models
 
 
class Migration(migrations.Migration):
 
    dependencies = [
        # Ajusta este número al último que tengas en tu carpeta migrations
        ('app', '0014_alter_targeta_direccion_casa_and_more'),
    ]
 
    operations = [
        migrations.AddField(
            model_name='targeta',
            name='frecuencia_cobro',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('DIARIO',    'Diario'),
                    ('SEMANAL',   'Semanal'),
                    ('QUINCENAL', 'Quincenal'),
                    ('MENSUAL',   'Mensual'),
                ],
                default='DIARIO',
            ),
        ),
    ]