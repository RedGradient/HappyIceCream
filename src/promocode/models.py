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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "promo_codes"

    def __str__(self) -> str:
        return self.code


class UserPromocode(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField(db_index=True)
    promocode_id = models.BigIntegerField(
        unique=True,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_promocodes"
