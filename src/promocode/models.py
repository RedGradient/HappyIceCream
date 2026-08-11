from typing import ClassVar

from django.core.validators import RegexValidator
from django.db import models

PROMO_CODE_VALIDATOR = RegexValidator(
    regex=r"^([A-Z]{8}|[0-9]{8})$",
    message="Промокод должен состоять из 8 заглавных латинских букв или из 8 цифр.",
)


class PromoCode(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(
        max_length=8, unique=True, validators=[PROMO_CODE_VALIDATOR]
    )

    # Выпадал ли промокод в прошлых розыгрышах
    is_drawn = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "promo_codes"
        indexes: ClassVar[list] = [
            models.Index(
                fields=["id"],
                name="promocode_undrawn_id_idx",
                condition=models.Q(is_drawn=False),
            ),
        ]

    def __str__(self) -> str:
        return self.code


class UserPromocode(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField(db_index=True)
    promocode_id = models.BigIntegerField(
        unique=True,
        db_index=True,
    )
    is_won = models.BooleanField(default=False)
    won_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_promocodes"
        indexes: ClassVar[list] = [
            models.Index(
                fields=["-won_on"],
                name="user_promocode_won_on_idx",
                condition=models.Q(won_on__isnull=False),
            ),
        ]
        constraints: ClassVar[list] = [
            # Один пользователь может победить только один раз
            models.UniqueConstraint(
                fields=["user_id"],
                condition=models.Q(is_won=True),
                name="unique_user_promocode_winner",
            ),
        ]

    def __str__(self) -> str:
        if self.is_won:
            return f"user={self.user_id} promo={self.promocode_id} won_on={self.won_on}"
        return f"user={self.user_id} promo={self.promocode_id}"
