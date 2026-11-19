import re
from pathlib import Path

from django.conf import settings
from django.template.backends.django import get_installed_libraries
from django.template.utils import get_app_template_dirs

LOAD = re.compile(r"{%\s*load\s+([^%]+?)\s*%}")


def template_paths():
    roots = [Path(directory) for directory in settings.TEMPLATES[0]["DIRS"]]
    roots.extend(Path(directory) for directory in get_app_template_dirs("templates"))
    for root in roots:
        yield from root.rglob("*.html")


def test_every_loaded_library_is_installed():
    installed = set(get_installed_libraries())
    missing = {}

    for path in template_paths():
        for match in LOAD.finditer(path.read_text(encoding="utf-8")):
            for name in match.group(1).split():
                if name not in installed:
                    missing.setdefault(name, set()).add(path.name)

    assert not missing, f"unregistered template libraries: {missing}"
