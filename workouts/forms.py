from django import forms

from parsing.csv_parser import MUSCLE_GUESS

from .models import ApiToken

MUSCLE_CHOICES = sorted({muscle for _, muscle in MUSCLE_GUESS} | {"Other"})


class UploadForm(forms.Form):
    csv_file = forms.FileField(label="Strong CSV export")


class MuscleGroupForm(forms.Form):
    exercise_name = forms.CharField(widget=forms.HiddenInput())
    muscle_group = forms.ChoiceField(choices=[(value, value) for value in MUSCLE_CHOICES])


class TokenForm(forms.Form):
    name = forms.CharField(max_length=255)

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_name(self):
        name = self.cleaned_data["name"]
        if self.owner is not None and ApiToken.objects.filter(owner=self.owner, name=name).exists():
            raise forms.ValidationError("A token with this name already exists.")
        return name
