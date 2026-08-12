from django import forms


class GeneratePromocodesForm(forms.Form):
    count = forms.IntegerField(
        label="Количество промокодов",
        min_value=1,
        max_value=5_000_000,
        initial=1_500_000,
    )


class ExcelFileForm(forms.Form):
    file = forms.FileField(
        label="Excel-файл",
        allow_empty_file=False,
    )
