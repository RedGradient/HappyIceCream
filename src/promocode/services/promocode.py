import logging
import secrets
import string
from collections.abc import Callable
from typing import Any

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from auth.models import User
from promocode.exceptions import (
    PromocodeAlreadyUsed,
    PromocodeDoesNotExist,
    UserProfileIncomplete,
)
from promocode.models import PromoActivation, Promocode
from promocode.services.winner import WinnerService

logger = logging.getLogger(__name__)

PROMO_CODE_ALPHABET_LETTERS = string.ascii_uppercase
PROMO_CODE_ALPHABET_NUMBERS = string.digits
PROMO_CODE_LENGTH = 8
PROMO_CODE_BATCH_SIZE = 25_000


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
        if not user.notify_on_promocode:
            return
        try:
            send_mail(
                subject="HappyIceCream",
                message=(
                    f"Промокод принят: {promocode.code}. "
                    f"Вы в розыгрыше Happy Ice Cream. Удачи!"
                ),
                from_email=None,
                recipient_list=[user.email],
            )
        except Exception:
            logger.exception(
                "Failed to send promocode email: user_id=%s email=%s code=%s",
                user.id,
                user.email,
                promocode.code,
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
        pool_from = WinnerService.pool_started_at()
        eligible = not user.winner
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
                "in_pool": (
                    eligible and pool_from is not None and row.created_at >= pool_from
                ),
            }
            for row in rows
        ]
