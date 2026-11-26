from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .context_processors import app_info
from .forms import LoginForm
from .releases import update_available


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(0)
        return response


@login_required
@require_GET
@never_cache
def release_status(request):
    return JsonResponse({"update_available": update_available()})


def not_found(request, exception):
    return render(request, "404.html", status=404)


def server_error(request):
    context = {**app_info(None), "user": AnonymousUser()}
    return HttpResponse(render_to_string("500.html", context), status=500)
