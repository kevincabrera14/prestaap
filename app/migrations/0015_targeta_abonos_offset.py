from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0014_alter_targeta_direccion_casa_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='targeta',
            name='abonos_offset',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=12,
                help_text='Suma de abonos de ciclos anteriores (para renovaciones sin borrar historial)',
            ),
        ),
    ]