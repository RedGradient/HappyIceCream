import logging
import secrets
from datetime import date
from typing import Any

from django.db import IntegrityError, transaction

from auth.models import User
from promocode.models import PromoActivation, Promocode
from promocode.services.promocode import PromoCodeService

logger = logging.getLogger(__name__)

TEST_SEED_PASSWORD = "testpass123"
GENERATE_PROMO_ATTEMPTS = 10


class TestDataService:
    """Создание тестовых User + Promocode + PromoActivation для локальной проверки."""

    @staticmethod
    def seed_participants(count: int) -> dict[str, Any]:
        if count <= 0:
            return {
                "users": 0,
                "promocodes": 0,
                "activations": 0,
                "password": TEST_SEED_PASSWORD,
            }

        created_users = 0
        created_promos = 0
        created_activations = 0
        promo_service = PromoCodeService()

        with transaction.atomic():
            for index in range(count):
                token = secrets.token_hex(4)
                username = f"test_{token}_{index}"
                email = f"test_{token}_{index}@example.com"
                user = User(
                    username=username,
                    email=email,
                    first_name="Тест",
                    last_name=f"Юзер{index + 1}",
                    middle_name="Тестович",
                    birth_date=date(1990, 1, 15),
                    telephone_number=f"+7900{index:07d}",
                    email_confirmed=True,
                    notify_on_promocode=False,
                    winner=False,
                )
                user.set_password(TEST_SEED_PASSWORD)
                user.save()
                created_users += 1

                promocode = None
                for _ in range(GENERATE_PROMO_ATTEMPTS):
                    code = promo_service._random_code()
                    if Promocode.objects.filter(code=code).exists():
                        continue
                    try:
                        # savepoint: IntegrityError не ломает внешний atomic
                        with transaction.atomic():
                            promocode = Promocode.objects.create(
                                code=code,
                                is_taken=True,
                            )
                        break
                    except IntegrityError:
                        continue
                if promocode is None:
                    raise RuntimeError("Не удалось сгенерировать уникальный промокод")

                PromoActivation.objects.create(user=user, promocode=promocode)
                created_promos += 1
                created_activations += 1

        logger.info(
            "Test seed created: users=%s promocodes=%s activations=%s",
            created_users,
            created_promos,
            created_activations,
        )
        return {
            "users": created_users,
            "promocodes": created_promos,
            "activations": created_activations,
            "password": TEST_SEED_PASSWORD,
        }
