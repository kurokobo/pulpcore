# Generated by Django 3.2.11 on 2022-02-09 12:55

from django.db import migrations, models
import django.db.models.deletion
import django_lifecycle.mixins
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0086_task_json_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskSchedule',
            fields=[
                ('pulp_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('pulp_created', models.DateTimeField(auto_now_add=True)),
                ('pulp_last_updated', models.DateTimeField(auto_now=True, null=True)),
                ('dispatch_interval', models.DurationField(null=True)),
                ('name', models.CharField(max_length=256, unique=True)),
                ('next_dispatch', models.DateTimeField(default=django.utils.timezone.now, null=True)),
                ('task_name', models.CharField(max_length=256)),
                ('last_task', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.task')),
            ],
            options={
                'abstract': False,
                'permissions': [('manage_roles_taskschedule', 'Can manage role assignments on task schedules')],
            },
            bases=(django_lifecycle.mixins.LifecycleModelMixin, models.Model),
        ),
    ]