from rest_framework import serializers


class NotifyOnPromocodeSerializer(serializers.Serializer):
    notify_on_promocode = serializers.BooleanField()


class UpdateProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
        default="",
    )
    last_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
        default="",
    )
    middle_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
        default="",
    )


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
