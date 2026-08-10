from promocode.models import PromoCode


class PromoCodeService:
    def check_code(self, code: str) -> bool:
        """
        Сравнивает промокод с ДБ и возвращает true/false
        в зависимости от того, существует ли код.
        """

        # 1. Проверка существования промокода
        try:
            _code = PromoCode.objects.get(code=code)
        except PromoCode.DoesNotExist:
            return False

        return True
