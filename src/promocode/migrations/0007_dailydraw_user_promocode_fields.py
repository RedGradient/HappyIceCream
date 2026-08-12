import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def split_user_promocode(apps, schema_editor):
    DailyDraw = apps.get_model("promocode", "DailyDraw")
    for draw in DailyDraw.objects.filter(user_promocode_id__isnull=False).iterator():
        user_promo = draw.user_promocode
        if user_promo is None:
            continue
        draw.user_id = user_promo.user_id
        draw.promocode_id = user_promo.promocode_id
        draw.save(update_fields=["user_id", "promocode_id"])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("promocode", "0006_daily_draw"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailydraw",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="daily_draws",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="dailydraw",
            name="promocode",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="daily_draws",
                to="promocode.promocode",
            ),
        ),
        migrations.RunPython(split_user_promocode, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="dailydraw",
            name="user_promocode",
        ),
    ]
