from django.db import migrations, models


def assign_place_one(apps, schema_editor):
    DailyDraw = apps.get_model("promocode", "DailyDraw")
    DailyDraw.objects.all().update(place=1)


class Migration(migrations.Migration):

    dependencies = [
        ("promocode", "0013_remove_is_drawn_add_user_winner"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailydraw",
            name="place",
            field=models.PositiveSmallIntegerField(null=True),
        ),
        migrations.RunPython(assign_place_one, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dailydraw",
            name="place",
            field=models.PositiveSmallIntegerField(),
        ),
        migrations.AlterField(
            model_name="dailydraw",
            name="date",
            field=models.DateField(),
        ),
        migrations.AlterModelOptions(
            name="dailydraw",
            options={"ordering": ["-date", "place"]},
        ),
        migrations.AddConstraint(
            model_name="dailydraw",
            constraint=models.UniqueConstraint(
                fields=("date", "place"),
                name="unique_daily_draw_date_place",
            ),
        ),
    ]
