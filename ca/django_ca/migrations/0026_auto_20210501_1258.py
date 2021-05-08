# Generated by Django 3.2 on 2021-05-01 12:58

from django.db import migrations
import django_ca.modelfields


class Migration(migrations.Migration):

    dependencies = [
        ('django_ca', '0025_auto_20210430_1132'),
    ]

    operations = [
        migrations.AlterField(
            model_name='certificate',
            name='pub',
            field=django_ca.modelfields.CertificateField(verbose_name='Public key'),
        ),
        migrations.AlterField(
            model_name='certificateauthority',
            name='pub',
            field=django_ca.modelfields.CertificateField(verbose_name='Public key'),
        ),
    ]