import io
import logging
import random
import secrets
import string
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from django.core.files.uploadedfile import UploadedFile
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from auth.models import User
from promocode.exceptions import (
    PromocodeAlreadyUsed,
    PromocodeDoesNotExist,
    UserProfileIncomplete,
    WinnerAlreadySelectedToday,
)
from promocode.models import (
    DailyDraw,
    Prize,
    PromoActivation,
    PromoAttempt,
    PromoAttemptReason,
    Promocode,
)

logger = logging.getLogger(__name__)

WINNERS_PER_DAY = 2
DAILY_PRIZES = (Prize.AIRPODS, Prize.OZON_COUPON)

PROMO_CODE_ALPHABET_LETTERS = string.ascii_uppercase
PROMO_CODE_ALPHABET_NUMBERS = string.digits
PROMO_CODE_LENGTH = 8
PROMO_CODE_BATCH_SIZE = 25_000

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
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[int, bool]:
        """
        Создаёт случайные буквенные и числовые промокоды батчами через bulk_create.

        Args:
            progress_callback: вызывается после каждого батча с (создано, цель).
            cancel_check: если возвращает True — генерация останавливается.

        Returns:
            (число вставленных строк, остановлено_флагом).
        """
        if count <= 0:
            return 0, False

        created_total = 0
        cancelled = False
        now = timezone.now()
        if progress_callback:
            progress_callback(0, count)

        while created_total < count:
            if cancel_check and cancel_check():
                cancelled = True
                logger.info(
                    "Promo codes generation cancelled: total_created=%s target=%s",
                    created_total,
                    count,
                )
                break

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
            if progress_callback:
                progress_callback(created_total, count)

            if inserted == 0:
                logger.warning(
                    "Promo codes batch inserted nothing, stopping early: "
                    "total_created=%s target=%s",
                    created_total,
                    count,
                )
                break

        return created_total, cancelled

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


class CabinetService:
    """Сводка для личного кабинета: участие и чеклист профиля."""

    @staticmethod
    def pool_started_at() -> datetime | None:
        return WinnerService.pool_started_at()

    @staticmethod
    def next_draw_at() -> datetime:
        """Ближайший розыгрыш — полночь по локальному времени (Europe/Moscow)."""
        tomorrow = timezone.localdate() + timedelta(days=1)
        return timezone.make_aware(
            datetime.combine(tomorrow, datetime.min.time()),
            timezone.get_current_timezone(),
        )

    def participation(self, user: User) -> dict[str, Any]:
        pool_from = self.pool_started_at()
        next_draw = self.next_draw_at()
        eligible = not user.winner
        if pool_from is None or not eligible:
            codes_count = 0
        else:
            codes_count = PromoActivation.objects.filter(
                user=user,
                created_at__gte=pool_from,
            ).count()

        return {
            "codes_count": codes_count,
            "eligible": eligible,
            "already_won": user.winner,
            "collection_until": next_draw,
            "next_draw_at": next_draw,
        }

    @staticmethod
    def profile_checklist(user: User) -> dict[str, Any]:
        items = [
            {
                "key": "name",
                "label": "Имя и фамилия",
                "done": bool(user.first_name and user.last_name),
            },
            {
                "key": "telephone",
                "label": "Телефон",
                "done": bool((user.telephone_number or "").strip()),
            },
            {
                "key": "birth_date",
                "label": "Дата рождения",
                "done": bool(user.birth_date),
            },
            {
                "key": "email",
                "label": "Email подтверждён",
                "done": bool(user.email_confirmed),
            },
        ]
        done_count = sum(1 for item in items if item["done"])
        return {
            "items": items,
            "complete": done_count == len(items),
            "done_count": done_count,
            "total": len(items),
        }

    def summary(self, user: User) -> dict[str, Any]:
        return {
            "participation": self.participation(user),
            "checklist": self.profile_checklist(user),
            "email_confirmed": bool(user.email_confirmed),
            "email": user.email,
        }


class WinnerService:
    @staticmethod
    def pool_started_at() -> datetime | None:
        """Нижняя граница пула следующего розыгрыша (как в get_random_winner)."""
        last_draw = DailyDraw.objects.order_by("-created_at").first()
        if last_draw:
            return last_draw.created_at
        first = PromoActivation.objects.order_by("created_at").first()
        return first.created_at if first else None

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
            "next_draw_at": CabinetService.next_draw_at(),
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

    def get_random_winner(self) -> list[DailyDraw]:
        """
        Выбирает до WINNERS_PER_DAY победителей за текущий день.

        Призы из DAILY_PRIZES раздаются случайно по заполненным местам
        (AirPods и купон OZON).

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
            self._notify_winner(
                draw.user,
                draw.promocode,
                today,
                draw.get_prize_display(),
            )
            logger.info(
                "Winner selected: place=%s prize=%s user_id=%s "
                "promocode_id=%s code=%s won_on=%s",
                draw.place,
                draw.prize,
                draw.user_id,
                draw.promocode_id,
                draw.promocode.code,
                today,
            )
        return winners

    def _notify_winner(
        self,
        user: User,
        promocode: Promocode,
        date: date,
        prize_label: str,
    ):
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


class AnalyticsService:
    @staticmethod
    def summary() -> dict[str, Any]:
        """Сводные метрики для админки."""

        today = timezone.localdate()
        week_ago = timezone.now() - timedelta(days=7)
        pool = WinnerService.current_pool_summary()

        users_profile_complete = (
            User.objects.filter(
                email_confirmed=True,
                birth_date__isnull=False,
            )
            .exclude(first_name="")
            .exclude(last_name="")
            .exclude(telephone_number__isnull=True)
            .exclude(telephone_number="")
            .count()
        )

        attempts_today = PromoAttempt.objects.filter(created_at__date=today)
        attempts_week = PromoAttempt.objects.filter(created_at__gte=week_ago)

        draw_days_incomplete = (
            DailyDraw.objects.values("date")
            .annotate(winners=Count("id", filter=Q(user__isnull=False)))
            .filter(winners__lt=WINNERS_PER_DAY)
            .count()
        )

        return {
            "users_total": User.objects.count(),
            "users_email_confirmed": User.objects.filter(email_confirmed=True).count(),
            "users_profile_complete": users_profile_complete,
            "unique_participants": (
                User.objects.filter(user_promocodes__isnull=False).distinct().count()
            ),
            "users_winners": User.objects.filter(winner=True).count(),
            "activations_total": PromoActivation.objects.count(),
            "activations_today": PromoActivation.objects.filter(
                created_at__date=today
            ).count(),
            "activations_7d": PromoActivation.objects.filter(
                created_at__gte=week_ago
            ).count(),
            "free_promocodes": Promocode.objects.filter(is_taken=False).count(),
            "pool_activations": pool["count"],
            "pool_unique_users": pool["unique_users"],
            "pool_activated_from": pool["activated_from"],
            "next_draw_at": pool["next_draw_at"],
            "winners_total": DailyDraw.objects.filter(user__isnull=False).count(),
            "winners_today": DailyDraw.objects.filter(
                date=today, user__isnull=False
            ).count(),
            "winners_airpods": DailyDraw.objects.filter(
                user__isnull=False, prize=Prize.AIRPODS
            ).count(),
            "winners_ozon": DailyDraw.objects.filter(
                user__isnull=False, prize=Prize.OZON_COUPON
            ).count(),
            "days_without_full_draw": draw_days_incomplete,
            "attempts_today": attempts_today.count(),
            "attempts_7d": attempts_week.count(),
            "attempts_today_not_found": attempts_today.filter(
                reason=PromoAttemptReason.NOT_FOUND
            ).count(),
            "attempts_today_already_used": attempts_today.filter(
                reason=PromoAttemptReason.ALREADY_USED
            ).count(),
            "attempts_7d_not_found": attempts_week.filter(
                reason=PromoAttemptReason.NOT_FOUND
            ).count(),
            "attempts_7d_already_used": attempts_week.filter(
                reason=PromoAttemptReason.ALREADY_USED
            ).count(),
        }

    @staticmethod
    def export_analytics_as_excel() -> tuple[bytes, str]:
        metrics = AnalyticsService.summary()
        labels = {
            "users_total": "Зарегистрировались",
            "users_email_confirmed": "Подтвердили email",
            "users_profile_complete": ("Заполнили ФИО, телефон, дату рождения и email"),
            "unique_participants": "Ввели хотя бы один промокод",
            "users_winners": "Уже выиграли (больше не участвуют)",
            "activations_total": "Промокодов активировано всего",
            "activations_today": "Промокодов активировано сегодня",
            "activations_7d": "Промокодов активировано за 7 дней",
            "free_promocodes": "Промокодов ещё не введено",
            "pool_activations": "Промокодов участвует в розыгрыше",
            "pool_unique_users": "Людей участвует в розыгрыше",
            "pool_activated_from": "Учитываются промокоды с",
            "next_draw_at": "Когда следующий розыгрыш",
            "winners_total": "Сколько раз выбрали победителя",
            "winners_today": "Победителей выбрано сегодня",
            "winners_airpods": "Выдали AirPods",
            "winners_ozon": "Выдали купон OZON",
            "days_without_full_draw": ("Дней, когда выбрали меньше 2 победителей"),
            "attempts_today": "Ошибок ввода сегодня",
            "attempts_today_not_found": "Сегодня ввели несуществующий код",
            "attempts_today_already_used": ("Сегодня ввели уже использованный код"),
            "attempts_7d": "Ошибок ввода за 7 дней",
            "attempts_7d_not_found": "За 7 дней: несуществующий код",
            "attempts_7d_already_used": "За 7 дней: уже использованный код",
        }
        rows = []
        for key, label in labels.items():
            value = metrics[key]
            if value is None:
                value = "—"
            elif isinstance(value, datetime):
                value = timezone.localtime(value).strftime("%d.%m.%Y %H:%M")
            elif isinstance(value, date):
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


TEST_SEED_PASSWORD = "testpass123"


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
