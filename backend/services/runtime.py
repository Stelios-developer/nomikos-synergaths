import os


def is_production():
    return any(os.getenv(key, "").strip().lower() == "production" for key in ("APP_ENV", "NODE_ENV"))
