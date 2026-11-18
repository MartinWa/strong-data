from django import forms

from parsing.csv_parser import MUSCLE_GUESS

MUSCLE_CHOICES = sorted({muscle for _, muscle in MUSCLE_GUESS} | {"Other"})


class UploadForm(forms.Form):
    csv_file = forms.FileField(label="Strong CSV export")


class MuscleGroupForm(forms.Form):
    exercise_name = forms.CharField(widget=forms.HiddenInput())
    muscle_group = forms.ChoiceField(choices=[(value, value) for value in MUSCLE_CHOICES])


class TokenForm(forms.Form):
    name = forms.CharField(max_length=255)
