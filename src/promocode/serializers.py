from rest_framework import serializers

from promocode.models import Promocode


class PromoCodeSerializer(serializers.Serializer):
    code = serializers.RegexField(
        regex=r"^([A-Z]{8}|[0-9]{8})$",
        max_length=8,
        min_length=8,
        error_messages={
            "required": "Укажите промокод.",
            "blank": "Укажите промокод.",
            "null": "Укажите промокод.",
            "invalid": (
                "Промокод должен состоять из 8 заглавных латинских букв или из 8 цифр."
            ),
            "min_length": "Промокод должен состоять из 8 символов.",
            "max_length": "Промокод должен состоять из 8 символов.",
        },
    )

    class Meta:
        model = Promocode
        fields = ("code",)
