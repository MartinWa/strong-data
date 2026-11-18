import os
import tomllib
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def app_version() -> str:
    return os.environ.get("STRONG_VERSION") or _pyproject_version()


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as stream:
        return tomllib.load(stream)["project"]["version"]
