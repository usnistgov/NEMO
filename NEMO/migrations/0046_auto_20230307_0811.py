# Generated by Django 3.2.18 on 2023-03-07 13:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0045_version_4_5_0'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='accounttype',
            options={'ordering': ['display_order', 'name']},
        ),
        migrations.AlterModelOptions(
            name='projectdiscipline',
            options={'ordering': ['display_order', 'name']},
        ),
        migrations.AlterModelOptions(
            name='usertype',
            options={'ordering': ['display_order', 'name']},
        ),
        migrations.AddField(
            model_name='accounttype',
            name='display_order',
            field=models.IntegerField(default=0, help_text='The display order is used to sort these items. The lowest value category is displayed first.'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='projectdiscipline',
            name='display_order',
            field=models.IntegerField(default=0, help_text='The display order is used to sort these items. The lowest value category is displayed first.'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='usertype',
            name='display_order',
            field=models.IntegerField(default=0, help_text='The display order is used to sort these items. The lowest value category is displayed first.'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='accounttype',
            name='name',
            field=models.CharField(help_text='The unique name for this item', max_length=200, unique=True),
        ),
        migrations.AlterField(
            model_name='usertype',
            name='name',
            field=models.CharField(help_text='The unique name for this item', max_length=200, unique=True),
        ),
        migrations.AlterField(
            model_name='interlock',
            name='unit_id',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Multiplier/Unit id'),
        ),
    ]
