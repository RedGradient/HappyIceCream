from django.apps import AppConfig


class AuthConfig(AppConfig):
    name = "auth"
    verbose_name = "Пользователи"

    # Указываем другой label, чтобы предотвратить конфликт имен приложений (в Django есть собственный auth)
    label = "user_auth"
