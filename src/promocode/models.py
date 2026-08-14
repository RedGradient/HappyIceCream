from typing import ClassVar

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

PROMO_CODE_VALIDATOR = RegexValidator(
    regex=r"^([A-Z]{8}|[0-9]{8})$",
    message="Промокод должен состоять из 8 заглавных латинских букв или из 8 цифр.",
)


class Promocode(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(
        max_length=8,
        unique=True,
        validators=[PROMO_CODE_VALIDATOR],
    )
    is_taken = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "promo_codes"
        indexes: ClassVar[list] = [
            models.Index(
                fields=["id"],
                name="promocode_free_id_idx",
                condition=models.Q(is_taken=False),
            ),
        ]

    def __str__(self) -> str:
        return self.code


class PromoActivation(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="user_promocodes",
        db_column="user_id",
    )
    promocode = models.OneToOneField(
        Promocode,
        on_delete=models.PROTECT,
        related_name="user_promocode",
        db_column="promocode_id",
    )
    is_won = models.BooleanField(default=False)
    won_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

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
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_won=True),
                name="unique_user_promocode_winner",
            ),
        ]

    def __str__(self) -> str:
        if self.is_won:
            return f"user={self.user_id} promo={self.promocode_id} won_on={self.won_on}"
        return f"user={self.user_id} promo={self.promocode_id}"


class DailyDraw(models.Model):
    """Одно место ежедневного розыгрыша (до WINNERS_PER_DAY на дату)."""

    id = models.BigAutoField(primary_key=True)
    date = models.DateField()
    place = models.PositiveSmallIntegerField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="daily_draws",
    )
    promocode = models.ForeignKey(
        Promocode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="daily_draws",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "daily_draws"
        ordering: ClassVar[list] = ["-date", "place"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["date", "place"],
                name="unique_daily_draw_date_place",
            ),
        ]

    def __str__(self) -> str:
        if self.user_id and self.promocode_id:
            return (
                f"{self.date} #{self.place}: "
                f"user={self.user_id} promo={self.promocode_id}"
            )
        return f"{self.date} #{self.place}: no winner"
