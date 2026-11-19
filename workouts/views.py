import hashlib
import hmac
import secrets
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from parsing import InvalidCSVError, parse_workouts

from . import pending
from .forms import MUSCLE_CHOICES, MuscleGroupForm, TokenForm, UploadForm
from .models import ApiToken, ExerciseMeta, WorkoutSession
from .services import EmptyImportError, import_workouts_csv

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
PENDING_IMPORT_KEY = "pending_import"
HISTORY_PAGE_SIZE = 25


def _discard_pending(request, import_id):
    pending.discard(import_id)
    request.session.pop(PENDING_IMPORT_KEY, None)


def _expired(request, import_id):
    _discard_pending(request, import_id)
    messages.error(request, "This preview expired. Upload the CSV again.")
    return redirect("upload")


@login_required
def upload(request):
    if request.method == "POST":
        content_length = request.META.get("CONTENT_LENGTH", "")
        size = int(content_length) if content_length.isdigit() else 0
        if size > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES:
            return render(
                request,
                "workouts/upload.html",
                {"form": UploadForm(), "too_large": True},
            )
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
                        previous = request.session.get(PENDING_IMPORT_KEY)
                        if previous:
                            pending.discard(previous["id"])
                        pending.purge_stale()
                        import_id = secrets.token_urlsafe(16)
                        try:
                            pending.save(import_id, raw, parsed)
                        except OSError:
                            form.add_error("csv_file", "The upload could not be stored. Try again.")
                        else:
                            request.session[PENDING_IMPORT_KEY] = {
                                "id": import_id,
                                "fingerprint": hashlib.sha256(raw.encode()).hexdigest(),
                                "created_at": time.time(),
                            }
                            return redirect("preview")
    else:
        form = UploadForm()
    return render(request, "workouts/upload.html", {"form": form})


@login_required
def preview(request):
    pending.purge_stale()
    stored = request.session.get(PENDING_IMPORT_KEY)
    if not stored:
        return redirect("upload")
    import_id = stored["id"]
    if time.time() - stored.get("created_at", 0) > pending.PENDING_TTL_SECONDS:
        return _expired(request, import_id)
    summary = pending.load_summary(import_id)
    if summary is None:
        return _expired(request, import_id)
    if request.method == "POST":
        posted_id = request.POST.get("import_id", "")
        posted_fingerprint = request.POST.get("fingerprint", "")
        if not hmac.compare_digest(
            posted_id.encode(), import_id.encode()
        ) or not hmac.compare_digest(posted_fingerprint.encode(), stored["fingerprint"].encode()):
            messages.error(request, "This preview is stale. Upload the CSV again.")
            return redirect("upload")
        raw = pending.load_csv(import_id)
        if raw is None:
            return _expired(request, import_id)
        try:
            result = import_workouts_csv(request.user, raw)
        except (EmptyImportError, InvalidCSVError) as exc:
            messages.error(request, str(exc))
            _discard_pending(request, import_id)
            return redirect("upload")
        _discard_pending(request, import_id)
        messages.success(
            request,
            f"Imported {result.sessions} sessions and {result.sets} sets.",
        )
        return redirect("history")
    return render(
        request,
        "workouts/preview.html",
        {
            "summary": summary,
            "import_id": import_id,
            "fingerprint": stored["fingerprint"],
        },
    )


@login_required
def history(request):
    pending.purge_stale()
    sessions = (
        WorkoutSession.objects.filter(owner=request.user)
        .order_by("-session_date", "-id")
        .prefetch_related("sets__exercise")
    )
    page = Paginator(sessions, HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "workouts/history.html", {"page": page})


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
        {"metas": metas, "form": form, "muscle_choices": MUSCLE_CHOICES},
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
                        expires_at=form.cleaned_data["expires_at"],
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
