import logging
from typing import Any

from django.db import IntegrityError

from auth.models import User
from promocode.exceptions import PromocodeAlreadyUsed, PromocodeDoesNotExists
from promocode.models import PromoCode, UserPromocode, Winner

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
        all_winners = Winner.objects.order_by("-won_on")[:limit]
        users = User.objects.in_bulk([row.user_id for row in all_winners])

        return [
            {"won_on": row.won_on, "name": users[row.user_id].get_full_name()}
            for row in all_winners
        ]
