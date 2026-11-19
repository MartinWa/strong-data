import os

os.environ["STRONG_SECRET_KEY"] = "test-only-secret-key-never-for-runtime-000000000000"

from strong_data.settings import *  # noqa: E402,F403
