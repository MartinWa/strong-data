from django import forms
from django.utils import timezone

from parsing.csv_parser import MUSCLE_GUESS

from .models import ApiToken

MUSCLE_CHOICES = sorted({muscle for _, muscle in MUSCLE_GUESS} | {"Other"})


class UploadForm(forms.Form):
    csv_file = forms.FileField(
        label="Strong CSV export",
        help_text="Up to 10 MB. Nothing is written until you confirm on the next page.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )


class MuscleGroupForm(forms.Form):
    exercise_name = forms.CharField(widget=forms.HiddenInput())
    muscle_group = forms.CharField(max_length=64)


class TokenForm(forms.Form):
    name = forms.CharField(max_length=255)
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Optional. The token stops working after this time.",
    )

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_name(self):
        name = self.cleaned_data["name"]
        if self.owner is not None and ApiToken.objects.filter(owner=self.owner, name=name).exists():
            raise forms.ValidationError("A token with this name already exists.")
        return name

    def clean_expires_at(self):
        expires_at = self.cleaned_data["expires_at"]
        if expires_at is not None and expires_at <= timezone.now():
            raise forms.ValidationError("Expiry must be in the future.")
        return expires_at
