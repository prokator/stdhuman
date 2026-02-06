from __future__ import annotations

import secrets
import shutil
import string
from pathlib import Path

from app.user_store import ensure_user_id_file

CODE_PATH = Path(".telegram_start_code")
CODE_LENGTH = 12
ALPHABET = string.ascii_letters + string.digits + "-_"


def _ensure_code_file() -> Path:
    if CODE_PATH.exists() and CODE_PATH.is_dir():
        shutil.rmtree(CODE_PATH, ignore_errors=True)
    return CODE_PATH


def _read_code(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if len(text) != CODE_LENGTH:
        return None
    if all(char in ALPHABET for char in text):
        return text
    return None


def _generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def initialize_auth_files() -> None:
    ensure_user_id_file()
    get_start_code()


def ensure_start_code_present() -> str:
    return get_start_code()


def get_start_code() -> str:
    code_file = _ensure_code_file()
    cached = _read_code(code_file)
    if cached:
        return cached
    code = _generate_code()
    code_file.write_text(code, encoding="utf-8")
    return code
