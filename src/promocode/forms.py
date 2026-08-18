from django import forms


class GeneratePromocodesForm(forms.Form):
    count = forms.IntegerField(
        label="Количество промокодов",
        min_value=1,
        max_value=5_000_000,
        initial=1_500_000,
    )


class SeedTestDataForm(forms.Form):
    count = forms.IntegerField(
        label="Количество участников",
        min_value=1,
        max_value=100,
        initial=5,
    )


class ExcelFileForm(forms.Form):
    file = forms.FileField(
        label="Excel-файл",
        allow_empty_file=False,
    )


class MetricsPeriodForm(forms.Form):
    date_from = forms.DateField(
        label="От",
        required=False,
        input_formats=["%Y-%m-%d", "%d.%m.%Y"],
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date"},
        ),
    )
    date_to = forms.DateField(
        label="До",
        required=False,
        input_formats=["%Y-%m-%d", "%d.%m.%Y"],
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date"},
        ),
    )

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            cleaned["date_from"], cleaned["date_to"] = date_to, date_from
        return cleaned
