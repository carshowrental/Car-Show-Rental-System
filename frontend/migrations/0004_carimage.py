# Generated by Django 4.2.16 on 2024-10-13 15:17

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0003_userprofile_address_userprofile_phone_number'),
    ]

    operations = [
        migrations.CreateModel(
            name='CarImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='car_images/')),
                ('is_main', models.BooleanField(default=False)),
                ('caption', models.CharField(blank=True, max_length=200)),
                ('car', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='carimages_set', to='frontend.car')),
            ],
            options={
                'ordering': ['-is_main', 'id'],
            },
        ),
    ]
