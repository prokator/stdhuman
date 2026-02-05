from __future__ import annotations

import shutil
from pathlib import Path

USER_ID_PATH = Path(".telegram_user_id")


def _resolve_user_id_file() -> Path:
    if USER_ID_PATH.exists() and USER_ID_PATH.is_dir():
        return USER_ID_PATH / "id"
    return USER_ID_PATH


def ensure_user_id_file() -> None:
    if USER_ID_PATH.exists() and USER_ID_PATH.is_dir():
        shutil.rmtree(USER_ID_PATH, ignore_errors=True)
    if not USER_ID_PATH.exists():
        USER_ID_PATH.write_text("", encoding="utf-8")


def get_cached_user_id() -> int | None:
    user_file = _resolve_user_id_file()
    if not user_file.exists():
        return None
    text = user_file.read_text(encoding="utf-8").strip()
    if not text.isdigit():
        return None
    return int(text)


def remember_user_id(user_id: int) -> None:
    user_file = _resolve_user_id_file()
    user_file.write_text(str(user_id), encoding="utf-8")
