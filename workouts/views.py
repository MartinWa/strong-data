import hashlib
import hmac
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from parsing import InvalidCSVError, parse_workouts

from .forms import MuscleGroupForm, TokenForm, UploadForm
from .models import ApiToken, ExerciseMeta, WorkoutSession
from .services import EmptyImportError, import_workouts_csv

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
                    parsed = parse_workouts(raw)
                except (UnicodeDecodeError, InvalidCSVError) as exc:
                    form.add_error("csv_file", str(exc))
                else:
                    if not parsed.sessions:
                        form.add_error("csv_file", "CSV export contains no importable rows")
                    else:
                        request.session[PENDING_IMPORT_KEY] = {
                            "id": secrets.token_urlsafe(16),
                            "fingerprint": hashlib.sha256(raw.encode()).hexdigest(),
                            "csv": raw,
                        }
                        return redirect("preview")
    else:
        form = UploadForm()
    return render(request, "workouts/upload.html", {"form": form})


@login_required
def preview(request):
    pending = request.session.get(PENDING_IMPORT_KEY)
    if not pending:
        return redirect("upload")
    parsed = parse_workouts(pending["csv"])
    if request.method == "POST":
        posted_id = request.POST.get("import_id", "")
        posted_fingerprint = request.POST.get("fingerprint", "")
        if not hmac.compare_digest(
            posted_id.encode(), pending["id"].encode()
        ) or not hmac.compare_digest(posted_fingerprint.encode(), pending["fingerprint"].encode()):
            messages.error(request, "This preview is stale. Upload the CSV again.")
            return redirect("upload")
        try:
            result = import_workouts_csv(request.user, pending["csv"])
        except EmptyImportError as exc:
            messages.error(request, str(exc))
            request.session.pop(PENDING_IMPORT_KEY, None)
            return redirect("upload")
        request.session.pop(PENDING_IMPORT_KEY, None)
        messages.success(
            request,
            f"Imported {result.sessions} sessions and {result.sets} sets.",
        )
        return redirect("history")
    return render(
        request,
        "workouts/preview.html",
        {
            "parsed": parsed,
            "import_id": pending["id"],
            "fingerprint": pending["fingerprint"],
        },
    )


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
        form = TokenForm(request.POST, owner=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    secret = secrets.token_urlsafe(32)
                    ApiToken.objects.create(
                        owner=request.user,
                        name=form.cleaned_data["name"],
                        key_hash=hashlib.sha256(secret.encode()).hexdigest(),
                        prefix=secret[:8],
                    )
            except IntegrityError:
                secret = None
                form.add_error("name", "A token with this name already exists.")
            else:
                messages.success(request, "Token created. Copy the secret now; it is shown once.")
    else:
        form = TokenForm(owner=request.user)
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
