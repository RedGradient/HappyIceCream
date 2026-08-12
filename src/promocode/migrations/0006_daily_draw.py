import django.db.models.deletion
from django.db import migrations, models


def backfill_daily_draws(apps, schema_editor):
    UserPromocode = apps.get_model("promocode", "UserPromocode")
    DailyDraw = apps.get_model("promocode", "DailyDraw")

    for row in (
        UserPromocode.objects.filter(is_won=True, won_on__isnull=False)
        .order_by("won_on", "id")
        .iterator()
    ):
        DailyDraw.objects.get_or_create(
            date=row.won_on,
            defaults={"user_promocode_id": row.id},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("promocode", "0005_promocode_is_taken_and_fks"),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyDraw",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("date", models.DateField(unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user_promocode",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="daily_draws",
                        to="promocode.userpromocode",
                    ),
                ),
            ],
            options={
                "db_table": "daily_draws",
                "ordering": ["-date"],
            },
        ),
        migrations.RunPython(backfill_daily_draws, migrations.RunPython.noop),
    ]
