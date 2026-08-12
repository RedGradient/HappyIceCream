import logging
import random
from datetime import date
from typing import Any

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from auth.models import User
from promocode.exceptions import (
    PromocodeAlreadyUsed,
    PromocodeDoesNotExists,
    WinnerAlreadySelectedToday,
)
from promocode.models import DailyDraw, Promocode, UserPromocode

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

    def _record_daily_draw(
        self,
        draw_date,
        user_promocode: UserPromocode | None = None,
    ) -> DailyDraw:
        try:
            return DailyDraw.objects.create(
                date=draw_date,
                user_promocode=user_promocode,
            )
        except IntegrityError as exc:
            raise WinnerAlreadySelectedToday(
                "Победитель сегодня уже определен."
            ) from exc

    def get_random_winner(self) -> UserPromocode | None:
        """
        Случайным образом выбирает победителя розыгрыша за текущий день.

        Создаёт DailyDraw на сегодня: с user_promocode при победе
        или без него, если победителя нет.

        Raises:
            WinnerAlreadySelectedToday: розыгрыш на сегодня уже закрыт.

        Returns:
            UserPromocode победителя либо None, если победителя нет.
        """

        today = timezone.localdate()
        if DailyDraw.objects.filter(date=today).exists():
            logger.info("Daily draw already recorded: date=%s", today)
            raise WinnerAlreadySelectedToday("Победитель сегодня уже определен.")

        logger.info("Starting daily winner selection: date=%s", today)

        attempts = 10
        promocode = self.get_random_unused_promocode(attempts=attempts)
        if not promocode:
            logger.warning(
                "No undrawn promo codes found; attempts count: %s",
                attempts,
            )
            self._record_daily_draw(today)
            return None

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

                self._record_daily_draw(today, user_and_promo)

            # Отправляем email победителю
            self._notify_winner(user_and_promo.user, user_and_promo.promocode, today)

            logger.info(
                "Winner selected: user_id=%s promocode_id=%s code=%s won_on=%s",
                user_and_promo.user_id,
                promocode.id,
                promocode.code,
                today,
            )
            return user_and_promo
        except UserPromocode.DoesNotExist:
            logger.info(
                "No winner today: taken promo has no user link, "
                "promocode_id=%s code=%s",
                promocode.id,
                promocode.code,
            )
            self._record_daily_draw(today)
            return None
        except IntegrityError as exc:
            if DailyDraw.objects.filter(date=today).exists():
                raise WinnerAlreadySelectedToday(
                    "Победитель сегодня уже определен."
                ) from exc
            logger.info(
                "No winner today: promo candidate rejected by integrity "
                "constraint, promocode_id=%s",
                promocode.id,
            )
            self._record_daily_draw(today)
            return None

    def _notify_winner(self, user: User, promocode: Promocode, date: date):
        send_mail(
            subject="Вы победили — Happy Ice Cream",
            message=(
                "Поздравляем! Вы победили в ежедневном розыгрыше Happy Ice Cream.\n\n"
                f"Дата: {date.strftime('%d.%m.%Y')}\n"
                f"Промокод: {promocode.code}\n\n"
                "Скоро свяжемся с вами по этому email, чтобы передать приз."
            ),
            from_email=None,
            recipient_list=[user.email],
        )
