# Generated by Django 3.1.3 on 2020-11-28 12:15

from django.db import migrations, models
import django_ca.models


class Migration(migrations.Migration):

    dependencies = [
        ('django_ca', '0035_certificateauthority_acme_requires_contact'),
    ]

    operations = [
        migrations.AddField(
            model_name='acmeaccount',
            name='acme_kid',
            field=models.URLField(default='http://example.com', unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='acmeaccount',
            name='slug',
            field=models.SlugField(default=django_ca.models.acme_slug, unique=True),
        ),
    ]
