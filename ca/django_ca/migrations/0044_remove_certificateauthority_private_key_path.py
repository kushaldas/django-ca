# Generated by Django 5.0.2 on 2024-02-22 20:53

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('django_ca', '0043_auto_20240221_2153'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='certificateauthority',
            name='private_key_path',
        ),
    ]