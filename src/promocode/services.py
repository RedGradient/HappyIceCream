import logging
import random
from typing import Any

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from auth.models import User
from promocode.exceptions import (
    NoWinnerFound,
    PromocodeAlreadyUsed,
    PromocodeDoesNotExists,
    WinnerAlreadySelectedToday,
)
from promocode.models import Promocode, UserPromocode

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
            with transaction.atomic():
                user = User.objects.get(id=user_id)
                try:
                    promocode = Promocode.objects.select_for_update().get(code=code)
                except Promocode.DoesNotExist as exc:
                    raise PromocodeDoesNotExists from exc

                if promocode.is_taken:
                    raise PromocodeAlreadyUsed

                user_promocode = UserPromocode.objects.create(
                    user=user,
                    promocode=promocode,
                )
                promocode.is_taken = True
                promocode.save(update_fields=["is_taken"])

            if user.notify_on_promocode:
                send_mail(
                    subject="HappyIceCream",
                    message=(
                        f"Промокод принят: {promocode.code}. "
                        f"Вы в розыгрыше Happy Ice Cream. Удачи!"
                    ),
                    from_email=None,
                    recipient_list=[user.email],
                )
        except PromocodeDoesNotExists:
            logger.info(
                "Promo code not found: code=%s user_id=%s",
                code,
                user_id,
            )
            raise
        except PromocodeAlreadyUsed:
            logger.info(
                "Promo code already used: code=%s user_id=%s",
                code,
                user_id,
            )
            raise
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

    def user_promocodes_list(self, user: User) -> list[dict[str, Any]]:
        rows = (
            UserPromocode.objects.filter(user=user)
            .select_related("promocode")
            .order_by("-created_at")
        )
        return [
            {
                "code": row.promocode.code,
                "created_at": row.created_at,
                "is_won": row.is_won,
            }
            for row in rows
        ]


class WinnerService:
    def winner_landing_list(self, limit: int) -> list[dict[str, Any]]:
        winners = (
            UserPromocode.objects.filter(is_won=True)
            .select_related("user")
            .order_by("-won_on")[:limit]
        )
        return [
            {
                "won_on": row.won_on,
                "name": row.user.get_full_name() or row.user.username,
            }
            for row in winners
        ]

    def get_random_unused_promocode(self, attempts: int) -> Promocode | None:
        # Кандидаты на розыгрыш: уже применённые, ещё не разыгранные
        candidates = Promocode.objects.filter(is_drawn=False, is_taken=True)
        lo = candidates.order_by("id").values_list("id", flat=True).first()
        hi = candidates.order_by("-id").values_list("id", flat=True).first()
        if lo is None:
            return None

        for _ in range(attempts):
            random_index = random.randint(lo, hi)
            promo = candidates.filter(id__gte=random_index).order_by("id").first()
            if promo is not None:
                return promo

        return candidates.order_by("id").first()

    def get_random_winner(self) -> UserPromocode:
        """
        Случайным образом выбирает победителя розыгрыша за текущий день.

        Берёт случайный ещё не разыгранный занятый промокод, отмечает победу
        и помечает промокод как is_drawn.

        Raises:
            WinnerAlreadySelectedToday: победитель на сегодня уже выбран.
            NoWinnerFound: не удалось найти подходящего кандидата.

        Returns:
            Запись UserPromocode победителя.
        """

        today = timezone.localdate()
        if UserPromocode.objects.filter(won_on=today).exists():
            logger.info("Winner already selected today: date=%s", today)
            raise WinnerAlreadySelectedToday("Победитель сегодня уже определен.")

        logger.info("Starting daily winner selection: date=%s attempts=%s", today, 50)

        attempts = 50
        for attempt in range(1, attempts + 1):
            promocode = self.get_random_unused_promocode(attempts=1)
            if not promocode:
                logger.warning(
                    "No undrawn taken promo codes left: attempt=%s",
                    attempt,
                )
                raise NoWinnerFound

            try:
                with transaction.atomic():
                    user_and_promo = UserPromocode.objects.select_for_update().get(
                        promocode_id=promocode.id
                    )
                    user_and_promo.is_won = True
                    user_and_promo.won_on = today
                    user_and_promo.save(update_fields=["is_won", "won_on"])

                    promocode.is_drawn = True
                    promocode.save(update_fields=["is_drawn"])

                    logger.info(
                        "Winner selected: user_id=%s promocode_id=%s code=%s "
                        "won_on=%s attempt=%s",
                        user_and_promo.user_id,
                        promocode.id,
                        promocode.code,
                        today,
                        attempt,
                    )
                    return user_and_promo
            except UserPromocode.DoesNotExist:
                logger.debug(
                    "Taken promo has no user link, retrying: promocode_id=%s "
                    "code=%s attempt=%s",
                    promocode.id,
                    promocode.code,
                    attempt,
                )
                continue
            except IntegrityError:
                logger.info(
                    "Promo candidate rejected by integrity constraint, retrying: "
                    "promocode_id=%s attempt=%s",
                    promocode.id,
                    attempt,
                )
                continue

        logger.warning(
            "Failed to select a winner after %s attempts: date=%s",
            attempts,
            today,
        )
        raise NoWinnerFound
