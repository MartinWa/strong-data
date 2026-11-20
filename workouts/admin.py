from django.contrib import admin

from .models import ApiToken, Exercise, ExerciseMeta, WorkoutSession, WorkoutSet


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return False
        match = request.resolver_match
        url_name = getattr(match, "url_name", None)
        if not url_name:
            return False
        own_prefix = f"{self.opts.app_label}_{self.opts.model_name}_"
        return not url_name.startswith(own_prefix)


@admin.register(Exercise)
class ExerciseAdmin(ReadOnlyAdmin):
    list_display = ("name", "owner")
    search_fields = ("name", "owner__username")
    list_select_related = ("owner",)


@admin.register(ExerciseMeta)
class ExerciseMetaAdmin(ReadOnlyAdmin):
    list_display = ("exercise_name", "muscle_group", "owner")
    list_filter = ("muscle_group",)
    search_fields = ("exercise_name", "muscle_group", "owner__username")
    list_select_related = ("owner",)


@admin.register(WorkoutSession)
class WorkoutSessionAdmin(ReadOnlyAdmin):
    list_display = (
        "session_date",
        "workout_name",
        "program",
        "set_count",
        "total_volume_kg",
        "duration_min",
        "owner",
    )
    list_filter = ("session_date",)
    search_fields = ("workout_name", "program", "owner__username")
    date_hierarchy = "session_date"
    ordering = ("-session_date", "-id")
    list_select_related = ("owner",)


@admin.register(WorkoutSet)
class WorkoutSetAdmin(ReadOnlyAdmin):
    list_display = (
        "set_time",
        "exercise",
        "set_order",
        "weight_kg",
        "reps",
        "rpe",
        "volume_kg",
        "est_1rm_kg",
        "session",
        "owner",
    )
    list_filter = ("set_time",)
    search_fields = ("exercise__name", "session__workout_name", "owner__username")
    date_hierarchy = "set_time"
    ordering = ("-set_time", "-set_order")
    list_select_related = ("exercise", "session", "owner")


@admin.register(ApiToken)
class ApiTokenAdmin(ReadOnlyAdmin):
    list_display = ("name", "owner", "prefix", "status", "created_at", "expires_at", "revoked_at")
    list_filter = ("revoked_at", "created_at")
    search_fields = ("name", "prefix", "owner__username")
    ordering = ("-created_at",)
    list_select_related = ("owner",)
    exclude = ("key_hash",)

    @admin.display(description="Status")
    def status(self, obj):
        if obj.revoked_at is not None:
            return "revoked"
        return "expired" if obj.is_expired else "active"
