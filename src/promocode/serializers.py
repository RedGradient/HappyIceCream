from rest_framework import serializers

from promocode.models import PromoCode


class PromoCodeSerializer(serializers.ModelSerializer):
    code = serializers.RegexField(
        regex=r"^([A-Z]{8}|[0-9]{8})$",
        max_length=8,
        min_length=8,
        error_messages={
            "invalid": "Промокод должен состоять из 8 заглавных латинских букв или из 8 цифр.",
        },
    )

    class Meta:
        model = PromoCode
        fields = ("code",)
