import logging

from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from promocode.models import Promocode
from promocode.services.promocode import PROMO_CODE_BATCH_SIZE, PROMO_CODE_LENGTH

logger = logging.getLogger(__name__)


class ExcelService:
    def load_from_excel(self, file: UploadedFile) -> int:
        """
        Читает xlsx/xls с одним столбцом промокодов и вставляет их в БД.

        Returns:
            Число реально вставленных строк.
        """
        import pandas as pd

        # Сброс указателя файла на всякий случай
        file.seek(0)
        # Создаем pandas DataFrame
        df = pd.read_excel(file, header=None, dtype=str)
        if df.empty:
            return 0

        # Записываем содержимое столбца в список
        raw_values = df.iloc[:, 0].tolist()
        codes: list[str] = []
        # Дедупликация
        seen: set[str] = set()
        for value in raw_values:
            code = self._normalize_code(value)
            if code is None or code in seen:
                continue
            seen.add(code)
            codes.append(code)

        # Нет промокодов - делать нечего. Выходим
        if not codes:
            return 0

        created_total = 0
        now = timezone.now()
        for start in range(0, len(codes), PROMO_CODE_BATCH_SIZE):
            # Откусываем batch от целого списка
            batch = codes[start : start + PROMO_CODE_BATCH_SIZE]
            before = Promocode.objects.count()

            # Загружаем промокоды в базу порциями (batch)
            Promocode.objects.bulk_create(
                [Promocode(code=code, created_at=now) for code in batch],
                ignore_conflicts=True,
                batch_size=PROMO_CODE_BATCH_SIZE,
            )
            # Подсчитываем, сколько промокодов создали
            inserted = Promocode.objects.count() - before
            created_total += inserted

            logger.info(
                "Excel promo codes batch inserted: batch=%s inserted=%s "
                "total_created=%s",
                len(batch),
                inserted,
                created_total,
            )

        return created_total

    @staticmethod
    def _normalize_code(value: object) -> str | None:
        """Приводит ячейку Excel к валидному промокоду или отбрасывает её"""

        if value is None:
            return None

        code = str(value).strip().upper()
        if not code or code == "NAN":
            return None

        # Excel/pandas иногда отдают числа как "12345678.0"
        if code.endswith(".0") and code[:-2].isdigit():
            code = code[:-2]

        if len(code) != PROMO_CODE_LENGTH:
            return None
        if code.isalpha() or code.isdigit():
            return code
        return None
