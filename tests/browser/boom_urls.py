from django.urls import path

from strong_data import urls as site_urls

handler404 = "strong_data.views.not_found"
handler500 = "strong_data.views.server_error"


def boom(request):
    raise RuntimeError("synthetic failure for the 500 handler test")


urlpatterns = [path("boom/", boom), *site_urls.urlpatterns]
