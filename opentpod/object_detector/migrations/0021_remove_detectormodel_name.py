# Generated by Django 2.2.10 on 2020-07-16 00:09

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('object_detector', '0020_auto_20200703_1905'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='detectormodel',
            name='name',
        ),
    ]
