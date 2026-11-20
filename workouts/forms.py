from django import forms
from django.utils import timezone

from parsing.csv_parser import MUSCLE_GUESS

from .models import ApiToken, ExerciseMeta

MUSCLE_CHOICES = sorted({muscle for _, muscle in MUSCLE_GUESS} | {"Other"})
CUSTOM_GROUP = "__custom__"


def clean_group_name(value):
    return " ".join((value or "").split())


def muscle_group_options(user):
    options = {choice.casefold(): choice for choice in MUSCLE_CHOICES}
    stored = (
        ExerciseMeta.objects.filter(owner=user)
        .order_by()
        .values_list("muscle_group", flat=True)
        .distinct()
    )
    for value in stored:
        name = clean_group_name(value)
        options.setdefault(name.casefold(), name)
    return [options[key] for key in sorted(options)]


class UploadForm(forms.Form):
    csv_file = forms.FileField(
        label="Strong CSV export",
        help_text="Up to 10 MB. Nothing is written until you confirm on the next page.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )


class MuscleGroupForm(forms.ModelForm):
    muscle_group_custom = forms.CharField(
        required=False,
        max_length=64,
        label="New group",
        widget=forms.TextInput(
            attrs={"class": "muscle-custom", "placeholder": "New group name", "maxlength": 64}
        ),
    )

    class Meta:
        model = ExerciseMeta
        fields = ("muscle_group",)
        error_messages = {"muscle_group": {"required": "Choose a muscle group."}}

    def __init__(self, *args, options=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = list(options or MUSCLE_CHOICES)
        self.canonical = {option.casefold(): option for option in self.options}
        current = clean_group_name(self.instance.muscle_group)
        selected = self.canonical.get(current.casefold(), current)
        if selected and selected not in self.options:
            self.options.append(selected)
        name = self.instance.exercise_name
        self.fields["muscle_group"] = forms.ChoiceField(
            choices=[(option, option) for option in self.options] + [(CUSTOM_GROUP, "Custom…")],
            required=False,
            widget=forms.Select(
                attrs={
                    "class": "muscle-select",
                    "aria-label": f"Muscle group for {name}",
                    "data-custom": CUSTOM_GROUP,
                    "data-initial": selected,
                }
            ),
        )
        self.fields["muscle_group_custom"].widget.attrs["aria-label"] = (
            f"New muscle group for {name}"
        )
        self.initial["muscle_group"] = selected
        self.custom_selected = self.data.get(self.add_prefix("muscle_group")) == CUSTOM_GROUP

    def clean(self):
        cleaned = super().clean()
        if "muscle_group" in self.errors:
            return cleaned
        choice = cleaned.get("muscle_group")
        if choice == CUSTOM_GROUP:
            value = clean_group_name(cleaned.get("muscle_group_custom"))
            if not value:
                self.add_error("muscle_group_custom", "Type a name for the new group.")
            else:
                cleaned["muscle_group"] = self.canonical.get(value.casefold(), value)
        elif not choice:
            self.add_error("muscle_group", "Choose a muscle group.")
        return cleaned


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
