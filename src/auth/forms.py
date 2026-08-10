from typing import ClassVar

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class SignUpForm(forms.ModelForm):
    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password_confirm = forms.CharField(
        label="Повтор пароля",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    consent = forms.BooleanField(
        label="Даю согласие на обработку персональных данных",
        required=True,
        error_messages={
            "required": "Необходимо согласие на обработку персональных данных.",
        },
    )

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "last_name",
            "first_name",
            "middle_name",
        )
        labels: ClassVar[dict[str, str]] = {
            "username": "Логин",
            "email": "Email",
            "last_name": "Фамилия",
            "first_name": "Имя",
            "middle_name": "Отчество",
        }

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        password_confirm = cleaned.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "Пароли не совпадают.")
        return cleaned
