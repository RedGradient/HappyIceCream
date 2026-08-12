import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_is_taken(apps, schema_editor):
    PromoCode = apps.get_model("promocode", "PromoCode")
    UserPromocode = apps.get_model("promocode", "UserPromocode")
    taken_ids = UserPromocode.objects.values_list("promocode_id", flat=True)
    PromoCode.objects.filter(id__in=taken_ids).update(is_taken=True)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("promocode", "0004_userpromocode_unique_winner"),
    ]

    operations = [
        migrations.AddField(
            model_name="promocode",
            name="is_taken",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.RunPython(backfill_is_taken, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name="promocode",
            name="promocode_undrawn_id_idx",
        ),
        migrations.AddIndex(
            model_name="promocode",
            index=models.Index(
                condition=models.Q(("is_taken", False)),
                fields=["id"],
                name="promocode_free_id_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="promocode",
            index=models.Index(
                condition=models.Q(("is_drawn", False), ("is_taken", True)),
                fields=["id"],
                name="promocode_undrawn_taken_id_idx",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="userpromocode",
            name="unique_user_promocode_winner",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="userpromocode",
                    name="user_id",
                ),
                migrations.RemoveField(
                    model_name="userpromocode",
                    name="promocode_id",
                ),
                migrations.AddField(
                    model_name="userpromocode",
                    name="user",
                    field=models.ForeignKey(
                        db_column="user_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="user_promocodes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                migrations.AddField(
                    model_name="userpromocode",
                    name="promocode",
                    field=models.OneToOneField(
                        db_column="promocode_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="user_promocode",
                        to="promocode.promocode",
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.AddConstraint(
            model_name="userpromocode",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_won", True)),
                fields=("user",),
                name="unique_user_promocode_winner",
            ),
        ),
    ]
