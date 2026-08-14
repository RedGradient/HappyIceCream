from typing import Any, ClassVar

from rest_framework import serializers

from auth.models import User


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
            "first_name": {"required": False, "allow_null": True, "allow_blank": True},
            "last_name": {"required": False, "allow_null": True, "allow_blank": True},
            "middle_name": {"required": False, "allow_null": True, "allow_blank": True},
            "birth_date": {"required": False, "allow_null": True},
            "telephone_number": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
            },
            "notify_on_promocode": {"required": False},
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
    old_password = serializers.CharField(min_length=8)
    new_password = serializers.CharField(min_length=8)
    new_password_confirm = serializers.CharField(min_length=8)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Пароли не совпадают."}
            )
        return attrs
