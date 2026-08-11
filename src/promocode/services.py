import logging
import random
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from auth.models import User
from promocode.exceptions import (
    NoWinnerFound,
    PromocodeAlreadyUsed,
    PromocodeDoesNotExists,
    WinnerAlreadySelectedToday,
)
from promocode.models import PromoCode, UserPromocode

logger = logging.getLogger(__name__)


class PromoCodeService:
    def apply(self, code: str, user_id: int) -> UserPromocode:
        """
        Привязывает существующий промокод к пользователю.

        Raises:
            PromocodeDoesNotExists: промокод не найден в справочнике.
            PromocodeAlreadyUsed: промокод уже был использован.

        Returns:
            Созданная запись UserPromocode.
        """

        try:
            promocode = PromoCode.objects.get(code=code)
            user_promocode = UserPromocode.objects.create(
                user_id=user_id,
                promocode_id=promocode.id,
            )
        except PromoCode.DoesNotExist as exc:
            logger.info(
                "Promo code not found: code=%s user_id=%s",
                code,
                user_id,
            )
            raise PromocodeDoesNotExists from exc
        except IntegrityError as exc:
            logger.info(
                "Promo code already used: code=%s user_id=%s",
                code,
                user_id,
            )
            raise PromocodeAlreadyUsed from exc

        logger.info(
            "Promo code applied: code=%s user_id=%s promocode_id=%s",
            code,
            user_id,
            promocode.id,
        )
        return user_promocode


class WinnerService:
    def winner_landing_list(self, limit: int) -> list[dict[str, Any]]:
        all_winners = UserPromocode.objects.filter(is_won=True).order_by("-won_on")[
            :limit
        ]
        users = User.objects.in_bulk([row.user_id for row in all_winners])

        return [
            {"won_on": row.won_on, "name": users[row.user_id].get_full_name()}
            for row in all_winners
        ]

    def get_random_unused_promocode(self, attempts: int) -> PromoCode | None:
        unused_promos = PromoCode.objects.filter(is_drawn=False)
        lo = unused_promos.order_by("id").values_list("id", flat=True).first()
        hi = unused_promos.order_by("-id").values_list("id", flat=True).first()
        if lo is None:
            return None

        for _ in range(attempts):
            random_index = random.randint(lo, hi)
            promo = unused_promos.filter(id__gte=random_index).order_by("id").first()
            if promo is not None:
                return promo

        return unused_promos.order_by("id").first()

    def get_random_winner(self) -> UserPromocode:
        # Проверяем, есть ли победитель за сегодня
        if UserPromocode.objects.filter(won_on=timezone.localdate()).exists():
            raise WinnerAlreadySelectedToday("Победитель сегодня уже определен.")

        attempts = 50
        for _ in range(attempts):
            promocode = self.get_random_unused_promocode(attempts=1)
            if not promocode:
                raise NoWinnerFound

            try:
                with transaction.atomic():
                    user_and_promo = UserPromocode.objects.select_for_update().get(
                        promocode_id=promocode.id
                    )
                    user_and_promo.is_won = True
                    user_and_promo.won_on = timezone.localdate()
                    user_and_promo.save(update_fields=["is_won", "won_on"])

                    promocode.is_drawn = True
                    promocode.save(update_fields=["is_drawn"])

                    return user_and_promo
            except UserPromocode.DoesNotExist:
                continue
            except IntegrityError:
                continue

        raise NoWinnerFound
