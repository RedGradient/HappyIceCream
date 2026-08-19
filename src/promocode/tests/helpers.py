from datetime import date

from auth.models import User
from promocode.models import Promocode


def create_promocode(code: str) -> Promocode:
    return Promocode.objects.create(
        code=code,
        is_taken=False,
    )


def create_user(**extra) -> User:
    defaults = {
        "username": "john_doe",
        "email": "john@example.com",
        "notify_on_promocode": True,
        "birth_date": date(1990, 1, 15),
        "telephone_number": "+79001234567",
    }
    defaults.update(extra)
    return User.objects.create(**defaults)
