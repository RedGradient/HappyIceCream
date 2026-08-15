import logging
import random
from datetime import date, datetime, timedelta
from typing import Any

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from auth.models import User
from promocode.exceptions import WinnerAlreadySelectedToday
from promocode.models import DailyDraw, Prize, PromoActivation, Promocode

logger = logging.getLogger(__name__)

WINNERS_PER_DAY = 2
DAILY_PRIZES = (Prize.AIRPODS, Prize.OZON_COUPON)


class WinnerService:
    @staticmethod
    def pool_started_at() -> datetime | None:
        """Нижняя граница пула следующего розыгрыша (как в get_random_winner)."""
        last_draw = DailyDraw.objects.order_by("-created_at").first()
        if last_draw:
            return last_draw.created_at
        first = PromoActivation.objects.order_by("created_at").first()
        return first.created_at if first else None

    @staticmethod
    def next_draw_at() -> datetime:
        """Ближайший розыгрыш — полночь по локальному времени (Europe/Moscow)."""
        tomorrow = timezone.localdate() + timedelta(days=1)
        return timezone.make_aware(
            datetime.combine(tomorrow, datetime.min.time()),
            timezone.get_current_timezone(),
        )

    @classmethod
    def current_pool_queryset(cls) -> tuple[QuerySet[PromoActivation], datetime | None]:
        """
        Активации, участвующие в ближайшем розыгрыше.

        Returns:
            (queryset, activated_from) — queryset может быть пустым.
        """
        activated_from = cls.pool_started_at()
        if activated_from is None:
            return PromoActivation.objects.none(), None

        qs = (
            PromoActivation.objects.filter(
                user__winner=False,
                created_at__gte=activated_from,
            )
            .select_related("user", "promocode")
            .order_by("-created_at", "id")
        )
        return qs, activated_from

    @classmethod
    def current_pool_summary(cls) -> dict[str, Any]:
        qs, activated_from = cls.current_pool_queryset()
        return {
            "count": qs.count(),
            "unique_users": qs.values("user_id").distinct().count(),
            "activated_from": activated_from,
            "next_draw_at": cls.next_draw_at(),
        }

    def winners_by_day(self, days: int) -> list[dict[str, Any]]:
        """
        Победители, сгруппированные по датам (новые дни первыми).

        Args:
            days: сколько последних дней розыгрыша вернуть.
        """
        dates = list(
            DailyDraw.objects.order_by("-date")
            .values_list("date", flat=True)
            .distinct()[:days]
        )
        if not dates:
            return []

        def name_or_none(user: User | None) -> str | None:
            if not user:
                return None
            return user.get_full_name() or user.username

        rows = (
            DailyDraw.objects.filter(date__in=dates)
            .select_related("user")
            .order_by("-date", "place")
        )

        by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in dates}
        for row in rows:
            by_date[row.date].append(
                {
                    "place": row.place,
                    "prize": row.prize,
                    "prize_label": row.get_prize_display() if row.prize else None,
                    "name": name_or_none(row.user),
                }
            )

        return [
            {
                "date": draw_date,
                "winners": by_date[draw_date],
            }
            for draw_date in dates
        ]

    @staticmethod
    def clear_today_draw() -> bool:
        """
        Удаляет сегодняшние DailyDraw и откатывает отметки победителей (User.winner) за сегодня.

        Returns:
            True, если хотя бы одна запись розыгрыша была удалена.
        """
        today = timezone.localdate()
        with transaction.atomic():
            draws = list(DailyDraw.objects.select_for_update().filter(date=today))
            if not draws:
                return False

            winner_user_ids = [draw.user_id for draw in draws if draw.user_id]
            if winner_user_ids:
                PromoActivation.objects.filter(
                    user_id__in=winner_user_ids,
                    is_won=True,
                    won_on=today,
                ).update(is_won=False, won_on=None)
                still_winners = set(
                    PromoActivation.objects.filter(
                        user_id__in=winner_user_ids,
                        is_won=True,
                    ).values_list("user_id", flat=True)
                )
                reset_ids = [
                    user_id
                    for user_id in winner_user_ids
                    if user_id not in still_winners
                ]
                if reset_ids:
                    User.objects.filter(pk__in=reset_ids).update(winner=False)

            deleted, _ = DailyDraw.objects.filter(date=today).delete()
            logger.info(
                "Cleared daily draw for redo: date=%s deleted=%s",
                today,
                deleted,
            )
            return deleted > 0

    @staticmethod
    def _get_random_promocode(activated_from: datetime) -> PromoActivation | None:
        """
        Возвращает случайную активацию из пула кандидатов на розыгрыш.

        В пул входят активации с created_at >= activated_from у пользователей,
        которые ещё не побеждали (user.winner=False).

        Args:
            activated_from: нижняя граница пула (created_at прошлого
                DailyDraw или первой активации).

        Returns:
            Случайная PromoActivation из пула либо None, если пул пуст.
        """

        candidates = PromoActivation.objects.filter(
            user__winner=False,
            created_at__gte=activated_from,
        ).order_by("id")

        count = candidates.count()
        if count == 0:
            return None

        return candidates[random.randrange(count)]

    def _claim_activation(
        self,
        activation: PromoActivation,
        draw: DailyDraw,
        today: date,
        prize: str,
    ) -> PromoActivation | None:
        """Помечает активацию и пользователя победителем, заполняет место розыгрыша."""
        try:
            with transaction.atomic():
                promo_activation = PromoActivation.objects.select_for_update().get(
                    pk=activation.pk
                )
                promo_activation.is_won = True
                promo_activation.won_on = today
                promo_activation.save(update_fields=["is_won", "won_on"])

                user = promo_activation.user
                user.winner = True
                user.save(update_fields=["winner"])

                draw.user = promo_activation.user
                draw.promocode = promo_activation.promocode
                draw.prize = prize
                draw.save(update_fields=["user", "promocode", "prize"])
                return promo_activation
        except PromoActivation.DoesNotExist:
            logger.info(
                "No winner for place: activation disappeared, "
                "place=%s activation_id=%s promocode_id=%s",
                draw.place,
                activation.id,
                activation.promocode_id,
            )
            return None
        except IntegrityError:
            logger.info(
                "No winner for place: promo candidate rejected by integrity "
                "constraint, place=%s activation_id=%s promocode_id=%s",
                draw.place,
                activation.id,
                activation.promocode_id,
            )
            return None

    def get_random_winner(self, *, notify: bool = True) -> list[DailyDraw]:
        """
        Выбирает до WINNERS_PER_DAY победителей за текущий день.

        Призы из DAILY_PRIZES раздаются случайно по заполненным местам
        (AirPods и купон OZON).

        Args:
            notify: отправлять ли email победителям.

        Raises:
            WinnerAlreadySelectedToday: розыгрыш на сегодня уже закрыт.

        Returns:
            Список заполненных DailyDraw (может быть пустым).
        """

        today = timezone.localdate()
        winners: list[DailyDraw] = []

        activated_from: datetime | None = None
        if last_draw := DailyDraw.objects.order_by("-created_at").first():
            activated_from = last_draw.created_at

        try:
            with transaction.atomic():
                # Предотвращение гонки между Celery task и ручным запуском
                # place=1 захватывает день; place=2..N создаём в той же транзакции
                draws = [
                    DailyDraw.objects.create(date=today, place=place)
                    for place in range(1, WINNERS_PER_DAY + 1)
                ]

                if not activated_from:
                    promo_activation = PromoActivation.objects.order_by(
                        "created_at"
                    ).first()
                    if promo_activation:
                        activated_from = promo_activation.created_at

                assert activated_from is not None

                logger.info(
                    "Starting daily winner selection: draw_date=%s "
                    "places=%s pool_date_from=%s",
                    today,
                    WINNERS_PER_DAY,
                    activated_from,
                )

                prize_pool = list(DAILY_PRIZES)
                random.shuffle(prize_pool)

                for draw in draws:
                    activation = self._get_random_promocode(
                        activated_from=activated_from,
                    )
                    if not activation:
                        logger.warning(
                            "No candidate activations for place=%s pool_date_from=%s",
                            draw.place,
                            activated_from,
                        )
                        continue

                    if not prize_pool:
                        logger.warning("No prizes left for place=%s", draw.place)
                        continue

                    prize = prize_pool.pop()
                    claimed = self._claim_activation(activation, draw, today, prize)
                    if claimed is not None:
                        winners.append(draw)
        except IntegrityError as exc:
            logger.info("Daily draw already recorded: date=%s", today)
            raise WinnerAlreadySelectedToday(
                "Победитель сегодня уже определен."
            ) from exc

        for draw in winners:
            assert draw.user is not None
            assert draw.promocode is not None
            if notify:
                self._notify_winner(
                    draw.user,
                    draw.promocode,
                    today,
                    draw.get_prize_display(),
                )
            logger.info(
                "Winner selected: place=%s prize=%s user_id=%s "
                "promocode_id=%s code=%s won_on=%s notify=%s",
                draw.place,
                draw.prize,
                draw.user_id,
                draw.promocode_id,
                draw.promocode.code,
                today,
                notify,
            )
        return winners

    def _notify_winner(
        self,
        user: User,
        promocode: Promocode,
        date: date,
        prize_label: str,
    ) -> None:
        try:
            send_mail(
                subject="Вы победили — Happy Ice Cream",
                message=(
                    "Поздравляем! Вы победили в ежедневном розыгрыше Happy Ice Cream.\n\n"
                    f"Дата: {date.strftime('%d.%m.%Y')}\n"
                    f"Приз: {prize_label}\n"
                    f"Промокод: {promocode.code}\n\n"
                    "Скоро свяжемся с вами по этому email, чтобы передать приз."
                ),
                from_email=None,
                recipient_list=[user.email],
            )
        except Exception:
            logger.exception(
                "Failed to send winner email: user_id=%s email=%s "
                "promocode_id=%s prize=%s",
                user.id,
                user.email,
                promocode.id,
                prize_label,
            )
