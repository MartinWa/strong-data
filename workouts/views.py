import hashlib
import hmac
import secrets
import time
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.forms import modelformset_factory
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from parsing import InvalidCSVError, classify_muscle, parse_workouts

from . import pending
from .forms import (
    MUSCLE_CHOICES,
    MuscleGroupForm,
    TokenForm,
    UploadForm,
    clean_group_name,
    muscle_group_options,
)
from .limits import MAX_UPLOAD_BYTES, MULTIPART_OVERHEAD_BYTES
from .models import ApiToken, Exercise, ExerciseMeta, WorkoutSession, WorkoutSet
from .services import EmptyImportError, import_workouts_csv

MUSCLES_PAGE_SIZE = 100
ExerciseMetaFormSet = modelformset_factory(
    ExerciseMeta,
    form=MuscleGroupForm,
    extra=0,
    max_num=MUSCLES_PAGE_SIZE,
    absolute_max=MUSCLES_PAGE_SIZE,
)
PENDING_IMPORT_KEY = "pending_import"
SESSIONS_PAGE_SIZE = 25
TOO_LARGE_MESSAGE = "CSV export must be 10 MB or smaller. Choose a smaller file."
PREVIEW_MISSING_MESSAGE = "Your preview expired or was not found. Upload the CSV again."


def _discard_pending(request, import_id):
    pending.discard(import_id)
    request.session.pop(PENDING_IMPORT_KEY, None)


def _expired(request, import_id):
    _discard_pending(request, import_id)
    messages.error(request, "This preview expired. Upload the CSV again.")
    return redirect("upload")


def _optional_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _render_upload(request, form, too_large=None):
    if too_large:
        form.fields["csv_file"].widget.attrs["aria-describedby"] = (
            "id_csv_file_helptext id_csv_file_error"
        )
    return render(
        request,
        "workouts/upload.html",
        {
            "form": form,
            "too_large": too_large,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "too_large_message": TOO_LARGE_MESSAGE,
        },
    )


@login_required
def upload(request):
    if request.method == "POST":
        content_length = request.META.get("CONTENT_LENGTH", "")
        size = int(content_length) if content_length.isdigit() else 0
        if size > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES:
            return _render_upload(request, UploadForm(), too_large=TOO_LARGE_MESSAGE)
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload_file = form.cleaned_data["csv_file"]
            if upload_file.size > MAX_UPLOAD_BYTES:
                form.add_error("csv_file", TOO_LARGE_MESSAGE)
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
    return _render_upload(request, form)


@login_required
def preview(request):
    pending.purge_stale()
    stored = request.session.get(PENDING_IMPORT_KEY)
    if not stored:
        messages.warning(request, PREVIEW_MISSING_MESSAGE)
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
        if request.POST.get("action") == "cancel":
            _discard_pending(request, import_id)
            messages.info(request, "Preview discarded. Nothing was imported.")
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
        return redirect("sessions")
    return render(
        request,
        "workouts/preview.html",
        {
            "summary": summary,
            "import_id": import_id,
            "fingerprint": stored["fingerprint"],
            "current_sessions": WorkoutSession.objects.filter(owner=request.user).count(),
            "current_sets": WorkoutSet.objects.filter(owner=request.user).count(),
        },
    )


@login_required
def sessions(request):
    pending.purge_stale()
    owned = WorkoutSession.objects.filter(owner=request.user)
    has_data = owned.exists()
    program = request.GET.get("program", "").strip()
    query = request.GET.get("q", "").strip()
    date_from = _optional_date(request.GET.get("from", ""))
    date_to = _optional_date(request.GET.get("to", ""))
    filtered = bool(program or query or date_from or date_to)

    selected = owned
    if program:
        selected = selected.filter(program=program)
    if date_from:
        selected = selected.filter(session_date__gte=date_from)
    if date_to:
        selected = selected.filter(session_date__lte=date_to)
    if query:
        selected = selected.filter(
            Q(workout_name__icontains=query) | Q(sets__exercise__name__icontains=query)
        ).distinct()

    selected = selected.order_by("-session_date", "-id").prefetch_related("sets__exercise")
    page = Paginator(selected, SESSIONS_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "workouts/sessions.html",
        {
            "page": page,
            "has_data": has_data,
            "filtered": filtered,
            "total_sessions": owned.count(),
            "programs": owned.values_list("program", flat=True).distinct().order_by("program"),
            "selected_program": program,
            "query": query,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        },
    )


@login_required
@require_POST
def delete_sessions(request):
    owned = WorkoutSession.objects.filter(owner=request.user)
    session_total = owned.count()
    set_total = WorkoutSet.objects.filter(owner=request.user).count()
    with transaction.atomic():
        owned.delete()
        Exercise.objects.filter(owner=request.user).delete()
    messages.success(
        request,
        f"Deleted {session_total} session{'' if session_total == 1 else 's'} "
        f"and {set_total} set{'' if set_total == 1 else 's'}.",
    )
    return redirect("sessions")


def _merge_group_spellings(forms):
    spellings = {}
    for form in forms:
        if not form.has_changed():
            continue
        value = form.cleaned_data.get("muscle_group")
        if value:
            spellings.setdefault(value.casefold(), set()).add(value)
    resolved = {key: min(values) for key, values in spellings.items()}
    for form in forms:
        value = form.cleaned_data.get("muscle_group")
        if value and form.has_changed():
            form.instance.muscle_group = resolved[value.casefold()]


def _muscle_change_message(changed):
    if not changed:
        return "No changes to save."
    if len(changed) == 1:
        meta = changed[0].instance
        return f"{meta.exercise_name} → {meta.muscle_group} saved."
    return f"Saved {len(changed)} muscle groups."


def _custom_groups(user):
    built_in = {choice.casefold() for choice in MUSCLE_CHOICES}
    counts = (
        ExerciseMeta.objects.filter(owner=user)
        .order_by()
        .values("muscle_group")
        .annotate(total=Count("id"))
    )
    return [
        {"name": row["muscle_group"], "total": row["total"]}
        for row in sorted(counts, key=lambda row: row["muscle_group"].casefold())
        if row["muscle_group"].casefold() not in built_in
    ]


@login_required
def muscles(request):
    options = muscle_group_options(request.user)
    owned = ExerciseMeta.objects.filter(owner=request.user)
    page = Paginator(owned, MUSCLES_PAGE_SIZE).get_page(
        request.POST.get("page") or request.GET.get("page")
    )
    formset = ExerciseMetaFormSet(
        request.POST or None,
        queryset=page.object_list,
        form_kwargs={"options": options},
    )
    if request.method == "POST" and formset.is_valid():
        _merge_group_spellings(formset.forms)
        changed = [form for form in formset.forms if form.has_changed()]
        formset.save()
        messages.success(request, _muscle_change_message(changed))
        return redirect(f"{reverse('muscles')}?page={page.number}")
    return render(
        request,
        "workouts/muscles.html",
        {
            "formset": formset,
            "page": page,
            "count": owned.count(),
            "custom_groups": _custom_groups(request.user),
        },
    )


@login_required
@require_POST
def delete_group(request):
    name = clean_group_name(request.POST.get("group"))
    built_in = {choice.casefold() for choice in MUSCLE_CHOICES}
    if not name or name.casefold() in built_in:
        messages.error(request, "That group cannot be deleted.")
        return redirect("muscles")
    metas = list(ExerciseMeta.objects.filter(owner=request.user, muscle_group=name))
    if not metas:
        messages.info(request, f"No exercise uses {name}.")
        return redirect("muscles")
    for meta in metas:
        meta.muscle_group = classify_muscle(meta.exercise_name)
        meta.save(update_fields=["muscle_group"])
    messages.success(
        request,
        f"Deleted {name}. "
        f"{len(metas)} exercise{'' if len(metas) == 1 else 's'} reverted to the guessed group.",
    )
    return redirect("muscles")


@login_required
def tokens(request):
    user_tokens = ApiToken.objects.filter(owner=request.user)
    secret = None
    created_name = ""
    if request.method == "POST":
        form = TokenForm(request.POST, owner=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    secret = secrets.token_urlsafe(32)
                    created_name = form.cleaned_data["name"]
                    ApiToken.objects.create(
                        owner=request.user,
                        name=created_name,
                        key_hash=hashlib.sha256(secret.encode()).hexdigest(),
                        prefix=secret[:8],
                        expires_at=form.cleaned_data["expires_at"],
                    )
            except IntegrityError:
                secret = None
                created_name = ""
                form.add_error("name", "A token with this name already exists.")
            else:
                messages.success(
                    request,
                    f"Created {created_name}. Copy the secret now; it is shown only once.",
                )
                form = TokenForm(owner=request.user)
    else:
        form = TokenForm(owner=request.user)
    return render(
        request,
        "workouts/tokens.html",
        {
            "tokens": user_tokens,
            "form": form,
            "secret": secret,
            "created_name": created_name,
            "has_sessions": WorkoutSession.objects.filter(owner=request.user).exists(),
        },
    )


@login_required
@require_POST
def revoke_token(request, pk):
    token = ApiToken.objects.filter(owner=request.user, pk=pk).first()
    if token is None:
        messages.error(request, "That token was not found.")
        return redirect("tokens")
    if token.revoked_at is not None:
        messages.info(request, f"{token.name} was already revoked.")
        return redirect("tokens")
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
    messages.success(request, f"Revoked {token.name}. Clients using it stop working now.")
    return redirect("tokens")


@login_required
@require_POST
def delete_token(request, pk):
    token = ApiToken.objects.filter(owner=request.user, pk=pk).first()
    if token is None:
        messages.error(request, "That token was not found.")
        return redirect("tokens")
    if token.is_active:
        messages.error(request, f"Revoke {token.name} first; a working token cannot be deleted.")
        return redirect("tokens")
    name = token.name
    token.delete()
    messages.success(request, f"Deleted {name}. That name can be used again.")
    return redirect("tokens")
