from django.core.management.base import BaseCommand

from promocode.models import Promocode

SEED_CODES = (
    "HAPPYICE",
    "VANILLAX",
    "STRAWBRY",
    "MINTCHIP",
    "12345678",
)


class Command(BaseCommand):
    help = "Seed promo codes for local development"

    def handle(self, *args, **options):
        created_count = 0

        for code in SEED_CODES:
            _, created = Promocode.objects.get_or_create(code=code)
            if created:
                created_count += 1
                self.stdout.write(f"Created {code}")
            else:
                self.stdout.write(f"Exists  {code}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created_count}, total seed codes: {len(SEED_CODES)}"
            )
        )
