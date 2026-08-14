import io
import logging
import random
import secrets
import string
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from django.core.files.uploadedfile import UploadedFile
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from auth.models import User
from promocode.exceptions import (
    PromocodeAlreadyUsed,
    PromocodeDoesNotExist,
    UserProfileIncomplete,
    WinnerAlreadySelectedToday,
)
from promocode.models import DailyDraw, PromoActivation, Promocode

logger = logging.getLogger(__name__)

PROMO_CODE_ALPHABET_LETTERS = string.ascii_uppercase
PROMO_CODE_ALPHABET_NUMBERS = string.digits
PROMO_CODE_LENGTH = 8
PROMO_CODE_BATCH_SIZE = 50_000

GENERATE_PROMO_ATTEMPTS = 10


class PromoCodeService:
    def apply(self, code: str, user_id: int) -> PromoActivation:
        """
        Привязывает существующий промокод к пользователю.

        Raises:
            PromocodeDoesNotExist: промокод не найден в справочнике.
            PromocodeAlreadyUsed: промокод уже был использован.
            UserProfileIncomplete: не заполнены обязательные поля профиля.

        Returns:
            Созданная запись PromoActivation.
        """

        try:
            with transaction.atomic():
                user = User.objects.get(id=user_id)
                if not user.birth_date or not (user.telephone_number or "").strip():
                    raise UserProfileIncomplete

                promocode = Promocode.objects.select_for_update().get(code=code)

                if promocode.is_taken:
                    logger.info(
                        "Promo code already used: code=%s user_id=%s",
                        code,
                        user_id,
                    )
                    raise PromocodeAlreadyUsed

                user_promocode = PromoActivation.objects.create(
                    user=user,
                    promocode=promocode,
                )
                promocode.is_taken = True
                promocode.save(update_fields=["is_taken"])

            self._notify_on_promocode(user, promocode)
        except Promocode.DoesNotExist as exc:
            logger.info(
                "Promo code not found: code=%s user_id=%s",
                code,
                user_id,
            )
            raise PromocodeDoesNotExist from exc
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

    @staticmethod
    def _notify_on_promocode(user: User, promocode: Promocode) -> None:
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

    @staticmethod
    def _random_code() -> str:
        """Создает случайный буквенный или числовой промокод"""

        # Выбираем промокод - буквенный или числовой
        alphabet = secrets.choice(
            [PROMO_CODE_ALPHABET_LETTERS, PROMO_CODE_ALPHABET_NUMBERS]
        )

        return "".join(secrets.choice(alphabet) for _ in range(PROMO_CODE_LENGTH))

    def generate_codes(
        self,
        count: int,
        batch_size: int = PROMO_CODE_BATCH_SIZE,
    ) -> int:
        """
        Создаёт случайные буквенные и числовые промокоды батчами через bulk_create.

        Returns:
            Число реально вставленных строк (с учётом ignore_conflicts).
        """
        if count <= 0:
            return 0

        created_total = 0
        now = timezone.now()

        while created_total < count:
            batch_count = min(batch_size, count - created_total)
            codes: set[str] = set()
            while len(codes) < batch_count:
                codes.add(self._random_code())

            before = Promocode.objects.count()
            Promocode.objects.bulk_create(
                [Promocode(code=code, created_at=now) for code in codes],
                ignore_conflicts=True,
                batch_size=batch_size,
            )
            inserted = Promocode.objects.count() - before
            created_total += inserted

            logger.info(
                "Promo codes batch inserted: requested=%s inserted=%s "
                "total_created=%s target=%s",
                batch_count,
                inserted,
                created_total,
                count,
            )
            if inserted == 0:
                logger.warning(
                    "Promo codes batch inserted nothing, stopping early: "
                    "total_created=%s target=%s",
                    created_total,
                    count,
                )
                break

        return created_total

    def user_promocodes_list(self, user: User) -> list[dict[str, Any]]:
        rows = (
            PromoActivation.objects.filter(user=user)
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
    def winners_list(self, limit: int) -> list[dict[str, Any]]:
        winners = (
            DailyDraw.objects.all().select_related("user").order_by("-date")[:limit]
        )

        def name_or_none(user: User | None) -> str | None:
            if not user:
                return None
            return user.get_full_name() or user.username

        return [
            {
                "date": row.date,
                "name": name_or_none(row.user),
            }
            for row in winners
        ]

    @staticmethod
    def clear_today_draw() -> bool:
        """
        Удаляет сегодняшний DailyDraw и откатывает отметки победителя за сегодня.

        Returns:
            True, если запись розыгрыша была удалена.
        """
        today = timezone.localdate()
        with transaction.atomic():
            draw = DailyDraw.objects.select_for_update().filter(date=today).first()
            if not draw:
                return False

            if draw.user_id:
                PromoActivation.objects.filter(
                    user_id=draw.user_id,
                    is_won=True,
                    won_on=today,
                ).update(is_won=False, won_on=None)
                if not PromoActivation.objects.filter(
                    user_id=draw.user_id,
                    is_won=True,
                ).exists():
                    User.objects.filter(pk=draw.user_id).update(winner=False)

            draw.delete()
            logger.info("Cleared daily draw for redo: date=%s", today)
            return True

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

    def _record_daily_draw(
        self,
        draw_date,
        user: User | None = None,
        promocode: Promocode | None = None,
    ) -> DailyDraw:
        try:
            return DailyDraw.objects.create(
                date=draw_date,
                user=user,
                promocode=promocode,
            )
        except IntegrityError as exc:
            raise WinnerAlreadySelectedToday(
                "Победитель сегодня уже определен."
            ) from exc

    def get_random_winner(self) -> PromoActivation | None:
        """
        Случайным образом выбирает победителя розыгрыша за текущий день.

        Создаёт DailyDraw на сегодня: с user и promocode при победе
        или без user, если победителя нет.

        Raises:
            WinnerAlreadySelectedToday: розыгрыш на сегодня уже закрыт.

        Returns:
            PromoActivation победителя либо None, если победителя нет.
        """

        today = timezone.localdate()
        winner: PromoActivation | None = None

        activated_from: datetime | None = None
        if last_draw := DailyDraw.objects.order_by("-created_at").first():
            activated_from = last_draw.created_at

        try:
            with transaction.atomic():
                # Захватываем день (unique date) — защита от гонки Celery/admin
                draw = DailyDraw.objects.create(date=today)

                # Если розыгрыши еще не проводились:
                # ставим границу пула кандидатов от даты самой первой активации промокода
                if not activated_from:
                    promo_activation = PromoActivation.objects.order_by(
                        "created_at"
                    ).first()
                    if promo_activation:
                        activated_from = promo_activation.created_at

                assert activated_from is not None

                logger.info(
                    "Starting daily winner selection: draw_date=%s pool_date_from=%s",
                    today,
                    activated_from,
                )

                activation = self._get_random_promocode(
                    activated_from=activated_from,
                )
                if not activation:
                    logger.warning(
                        "No candidate activations for pool_date_from=%s",
                        activated_from,
                    )
                    return None

                try:
                    with transaction.atomic():
                        promo_activation = (
                            PromoActivation.objects.select_for_update().get(
                                pk=activation.pk
                            )
                        )
                        promo_activation.is_won = True
                        promo_activation.won_on = today
                        promo_activation.save(update_fields=["is_won", "won_on"])

                        user = promo_activation.user
                        user.winner = True
                        user.save(update_fields=["winner"])

                        draw.user = promo_activation.user
                        draw.promocode = promo_activation.promocode
                        draw.save(update_fields=["user", "promocode"])
                        winner = promo_activation
                except PromoActivation.DoesNotExist:
                    logger.info(
                        "No winner today: activation disappeared, "
                        "activation_id=%s promocode_id=%s",
                        activation.id,
                        activation.promocode_id,
                    )
                    return None
                except IntegrityError:
                    logger.info(
                        "No winner today: promo candidate rejected by integrity "
                        "constraint, activation_id=%s promocode_id=%s",
                        activation.id,
                        activation.promocode_id,
                    )
                    return None
        except IntegrityError as exc:
            logger.info("Daily draw already recorded: date=%s", today)
            raise WinnerAlreadySelectedToday(
                "Победитель сегодня уже определен."
            ) from exc

        if winner is not None:
            self._notify_winner(winner.user, winner.promocode, today)
            logger.info(
                "Winner selected: user_id=%s promocode_id=%s code=%s won_on=%s",
                winner.user_id,
                winner.promocode_id,
                winner.promocode.code,
                today,
            )
        return winner

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


class AnalyticsService:
    @staticmethod
    def summary() -> dict[str, Any]:
        """Сводные метрики для админки."""

        today = timezone.localdate()
        # Кандидаты для следующего розыгрыша: если сегодня ещё не закрыт — показ активаций за вчера;
        # Если розыгрыш сегодня уже был — активации за сегодня (на завтра).
        if DailyDraw.objects.filter(date=today).exists():
            pool_date = today
            next_draw_date = today + timedelta(days=1)
        else:
            pool_date = today - timedelta(days=1)
            next_draw_date = today

        next_draw_candidates = PromoActivation.objects.filter(
            created_at__date=pool_date,
            user__winner=False,
        ).count()

        return {
            "users_total": User.objects.count(),
            "users_email_confirmed": User.objects.filter(email_confirmed=True).count(),
            "unique_participants": (
                User.objects.filter(user_promocodes__isnull=False).distinct().count()
            ),
            "activations_total": PromoActivation.objects.count(),
            "free_promocodes": Promocode.objects.filter(is_taken=False).count(),
            "next_draw_candidates": next_draw_candidates,
            "next_draw_date": next_draw_date,
            "pool_date": pool_date,
            "winners_total": DailyDraw.objects.filter(user__isnull=False).count(),
            "days_without_winner": DailyDraw.objects.filter(user__isnull=True).count(),
        }

    @staticmethod
    def export_analytics_as_excel() -> tuple[bytes, str]:
        metrics = AnalyticsService.summary()
        labels = {
            "users_total": "Всего пользователей",
            "users_email_confirmed": "Подтвердили email",
            "unique_participants": "Уникальные участники",
            "activations_total": "Всего активаций",
            "free_promocodes": "Свободные промокоды",
            "next_draw_candidates": "Кандидаты на следующий розыгрыш",
            "next_draw_date": "Дата следующего розыгрыша",
            "pool_date": "Дата пула кандидатов",
            "winners_total": "Победители за всё время",
            "days_without_winner": "Дни без победителя",
        }
        rows = []
        for key, label in labels.items():
            value = metrics[key]
            if isinstance(value, date):
                value = value.strftime("%d.%m.%Y")
            rows.append((label, value))

        df = pd.DataFrame(rows, columns=["Показатель", "Значение"])

        buffer = io.BytesIO()
        df.to_excel(buffer, index=False)
        filename = f"metrics-{timezone.localtime().strftime('%Y-%m-%d_%H-%M')}.xlsx"
        return buffer.getvalue(), filename


class ExcelService:
    def load_from_excel(self, file: UploadedFile) -> int:
        """
        Читает xlsx/xls с одним столбцом промокодов и вставляет их в БД.

        Returns:
            Число реально вставленных строк.
        """
        import pandas as pd

        # Сброс указателя файла на всякий случай
        file.seek(0)
        # Создаем pandas DataFrame
        df = pd.read_excel(file, header=None, dtype=str)
        if df.empty:
            return 0

        # Записываем содержимое столбца в список
        raw_values = df.iloc[:, 0].tolist()
        codes: list[str] = []
        # Дедупликация
        seen: set[str] = set()
        for value in raw_values:
            code = self._normalize_code(value)
            if code is None or code in seen:
                continue
            seen.add(code)
            codes.append(code)

        # Нет промокодов - делать нечего. Выходим
        if not codes:
            return 0

        created_total = 0
        now = timezone.now()
        for start in range(0, len(codes), PROMO_CODE_BATCH_SIZE):
            # Откусываем batch от целого списка
            batch = codes[start : start + PROMO_CODE_BATCH_SIZE]
            before = Promocode.objects.count()

            # Загружаем промокоды в базу порциями (batch)
            Promocode.objects.bulk_create(
                [Promocode(code=code, created_at=now) for code in batch],
                ignore_conflicts=True,
                batch_size=PROMO_CODE_BATCH_SIZE,
            )
            # Подсчитываем, сколько промокодов создали
            inserted = Promocode.objects.count() - before
            created_total += inserted

            logger.info(
                "Excel promo codes batch inserted: batch=%s inserted=%s "
                "total_created=%s",
                len(batch),
                inserted,
                created_total,
            )

        return created_total

    @staticmethod
    def _normalize_code(value: object) -> str | None:
        """Приводит ячейку Excel к валидному промокоду или отбрасывает её"""

        if value is None:
            return None

        code = str(value).strip().upper()
        if not code or code == "NAN":
            return None

        # Excel/pandas иногда отдают числа как "12345678.0"
        if code.endswith(".0") and code[:-2].isdigit():
            code = code[:-2]

        if len(code) != PROMO_CODE_LENGTH:
            return None
        if code.isalpha() or code.isdigit():
            return code
        return None
