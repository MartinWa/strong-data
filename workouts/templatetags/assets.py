import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def asset(path):
    url = static(path)
    if not settings.DEBUG:
        return url
    found = finders.find(path)
    if not found:
        return url
    return f"{url}?v={os.stat(found).st_mtime_ns}"
