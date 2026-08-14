from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("promocode", "0014_dailydraw_place"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailydraw",
            name="prize",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ozon_coupon", "Купон OZON"),
                    ("airpods", "AirPods"),
                ],
                max_length=32,
                null=True,
            ),
        ),
    ]
