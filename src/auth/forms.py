from typing import ClassVar

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class TelInput(forms.TextInput):
    input_type = "tel"


class EmailAuthenticationForm(AuthenticationForm):
    """Вход по email: поле username формы принимает адрес почты."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "autofocus": True,
            }
        ),
        error_messages={"invalid": "Неверный формат электронной почты"},
    )

    error_messages: ClassVar[dict[str, str]] = {
        **AuthenticationForm.error_messages,
        "invalid_login": (
            "Неверный email или пароль. Проверьте введённые данные "
            "или восстановите пароль."
        ),
    }


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
            "telephone_number",
        )
        labels: ClassVar[dict[str, str]] = {
            "username": "Логин",
            "email": "Email",
            "last_name": "Фамилия",
            "first_name": "Имя",
            "middle_name": "Отчество",
            "telephone_number": "Телефон",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "telephone_number": TelInput(
                attrs={
                    "autocomplete": "tel",
                    "maxlength": "32",
                }
            ),
        }
        error_messages: ClassVar[dict[str, dict[str, str]]] = {
            "email": {"invalid": "Неверный формат электронной почты"},
        }

    def clean_first_name(self):
        return self._blank_to_none(self.cleaned_data.get("first_name"))

    def clean_last_name(self):
        return self._blank_to_none(self.cleaned_data.get("last_name"))

    def clean_middle_name(self):
        return self._blank_to_none(self.cleaned_data.get("middle_name"))

    def clean_telephone_number(self):
        return self._blank_to_none(self.cleaned_data.get("telephone_number"))

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

    @staticmethod
    def _blank_to_none(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
        error_messages={"invalid": "Неверный формат электронной почты"},
    )


class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        label="Новый пароль",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password_confirm = forms.CharField(
        label="Повтор нового пароля",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password, user=self.user)
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        password_confirm = cleaned.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "Пароли не совпадают.")
        return cleaned
