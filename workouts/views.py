import hashlib
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from parsing import InvalidCSVError, parse_workouts

from .forms import MuscleGroupForm, TokenForm, UploadForm
from .models import ApiToken, ExerciseMeta, WorkoutSession
from .services import import_workouts_csv

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PENDING_IMPORT_KEY = "pending_import_csv"


@login_required
def upload(request):
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload_file = form.cleaned_data["csv_file"]
            if upload_file.size > MAX_UPLOAD_BYTES:
                form.add_error("csv_file", "CSV export must be 10 MB or smaller.")
            else:
                try:
                    raw = upload_file.read().decode("utf-8-sig")
                    parse_workouts(raw)
                except (UnicodeDecodeError, InvalidCSVError) as exc:
                    form.add_error("csv_file", str(exc))
                else:
                    request.session[PENDING_IMPORT_KEY] = raw
                    return redirect("preview")
    else:
        form = UploadForm()
    return render(request, "workouts/upload.html", {"form": form})


@login_required
def preview(request):
    raw = request.session.get(PENDING_IMPORT_KEY)
    if not raw:
        return redirect("upload")
    parsed = parse_workouts(raw)
    if request.method == "POST":
        result = import_workouts_csv(request.user, raw)
        request.session.pop(PENDING_IMPORT_KEY, None)
        messages.success(
            request,
            f"Imported {result.sessions} sessions and {result.sets} sets.",
        )
        return redirect("history")
    return render(request, "workouts/preview.html", {"parsed": parsed})


@login_required
def history(request):
    sessions = WorkoutSession.objects.filter(owner=request.user).prefetch_related("sets")
    return render(request, "workouts/history.html", {"sessions": sessions})


@login_required
def corrections(request):
    metas = ExerciseMeta.objects.filter(owner=request.user)
    if request.method == "POST":
        form = MuscleGroupForm(request.POST)
        if form.is_valid():
            updated = ExerciseMeta.objects.filter(
                owner=request.user,
                exercise_name=form.cleaned_data["exercise_name"],
            ).update(muscle_group=form.cleaned_data["muscle_group"])
            messages.success(request, "Muscle group updated." if updated else "Exercise not found.")
            return redirect("corrections")
    else:
        form = MuscleGroupForm()
    return render(
        request,
        "workouts/corrections.html",
        {"metas": metas, "form": form},
    )


@login_required
def tokens(request):
    user_tokens = ApiToken.objects.filter(owner=request.user)
    secret = None
    if request.method == "POST":
        form = TokenForm(request.POST)
        if form.is_valid():
            secret = secrets.token_urlsafe(32)
            ApiToken.objects.create(
                owner=request.user,
                name=form.cleaned_data["name"],
                key_hash=hashlib.sha256(secret.encode()).hexdigest(),
                prefix=secret[:8],
            )
            messages.success(request, "Token created. Copy the secret now; it is shown once.")
    else:
        form = TokenForm()
    return render(
        request,
        "workouts/tokens.html",
        {"tokens": user_tokens, "form": form, "secret": secret},
    )


@login_required
@require_POST
def revoke_token(request, pk):
    ApiToken.objects.filter(owner=request.user, pk=pk).update(revoked_at=timezone.now())
    return redirect("tokens")
