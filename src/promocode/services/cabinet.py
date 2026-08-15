import logging
from datetime import datetime
from typing import Any

from auth.models import User
from promocode.models import PromoActivation
from promocode.services.winner import WinnerService

logger = logging.getLogger(__name__)


class CabinetService:
    """Сводка для личного кабинета: участие и чеклист профиля."""

    @staticmethod
    def pool_started_at() -> datetime | None:
        return WinnerService.pool_started_at()

    @staticmethod
    def next_draw_at() -> datetime:
        return WinnerService.next_draw_at()

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
