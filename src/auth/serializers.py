from typing import Any, ClassVar

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from auth.models import User

_PASSWORD_ERRORS = {
    "required": "Обязательное поле.",
    "blank": "Обязательное поле.",
    "null": "Обязательное поле.",
    "min_length": "Пароль должен содержать не менее {min_length} символов.",
}


class AccountSerializer(serializers.ModelSerializer):
    """Личные данные текущего пользователя."""

    full_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "middle_name",
            "birth_date",
            "telephone_number",
            "notify_on_promocode",
            "email_confirmed",
            "full_name",
        )
        read_only_fields = ("email", "email_confirmed", "full_name")
        extra_kwargs: ClassVar[dict[str, Any]] = {
            "first_name": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "error_messages": {
                    "max_length": "Имя не должно быть длиннее {max_length} символов.",
                },
            },
            "last_name": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "error_messages": {
                    "max_length": "Фамилия не должна быть длиннее {max_length} символов.",
                },
            },
            "middle_name": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "error_messages": {
                    "max_length": "Отчество не должно быть длиннее {max_length} символов.",
                },
            },
            "birth_date": {
                "required": False,
                "allow_null": True,
                "error_messages": {
                    "invalid": "Введите корректную дату рождения.",
                },
            },
            "telephone_number": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "error_messages": {
                    "max_length": "Телефон не должен быть длиннее {max_length} символов.",
                },
            },
            "notify_on_promocode": {
                "required": False,
                "error_messages": {
                    "invalid": "Укажите корректное значение для уведомлений.",
                },
            },
        }

    def get_full_name(self, obj: User) -> str:
        return obj.get_full_name() or obj.username

    def validate_telephone_number(self, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    def validate_first_name(self, value: str | None) -> str | None:
        return self._blank_to_none(value)

    def validate_last_name(self, value: str | None) -> str | None:
        return self._blank_to_none(value)

    def validate_middle_name(self, value: str | None) -> str | None:
        return self._blank_to_none(value)

    @staticmethod
    def _blank_to_none(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        min_length=8,
        error_messages=_PASSWORD_ERRORS,
    )
    new_password = serializers.CharField(
        min_length=8,
        error_messages=_PASSWORD_ERRORS,
    )
    new_password_confirm = serializers.CharField(
        min_length=8,
        error_messages=_PASSWORD_ERRORS,
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Пароли не совпадают."}
            )
        user = self.context["request"].user
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"new_password": list(exc.messages)}
            ) from exc
        return attrs
