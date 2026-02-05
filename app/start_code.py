from __future__ import annotations

import hashlib
import os
import platform
import shutil
import secrets
import string
import sys
import uuid
from pathlib import Path

from app.user_store import ensure_user_id_file

SALT_ENV = "START_CODE_SALT"
SALT_PATH = Path(".telegram_start_salt")
MACHINE_ID_PATH = Path(".telegram_machine_id")
CODE_LENGTH = 12
ALPHABET = string.ascii_letters + string.digits + "-_"


def _read_machine_guid() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
    except Exception:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        if value:
            return str(value).strip()
    except Exception:
        return None
    return None


def _read_machine_id_file(path: str) -> str | None:
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return text or None


def _resolve_machine_id_file() -> Path:
    if MACHINE_ID_PATH.exists() and MACHINE_ID_PATH.is_dir():
        return MACHINE_ID_PATH / "id"
    return MACHINE_ID_PATH


def _coerce_file(path: Path, filename: str) -> str | None:
    if path.exists() and path.is_dir():
        candidate = path / filename
        content = None
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8").strip()
            candidate.unlink()
        try:
            path.rmdir()
        except OSError:
            pass
        if content:
            path.write_text(content, encoding="utf-8")
        return content
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def get_machine_id() -> str:
    cached = _coerce_file(MACHINE_ID_PATH, "id")
    if cached:
        return cached

    machine_file = _resolve_machine_id_file()
    if machine_file.exists():
        cached = machine_file.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    machine_guid = _read_machine_guid()
    if machine_guid:
        machine_id = f"guid:{machine_guid}"
        machine_file.write_text(machine_id, encoding="utf-8")
        return machine_id

    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        machine_id = _read_machine_id_file(path)
        if machine_id:
            machine_value = f"machine-id:{machine_id}"
            machine_file.write_text(machine_value, encoding="utf-8")
            return machine_value

    node = uuid.getnode()
    if node:
        machine_value = f"mac:{node:012x}"
        machine_file.write_text(machine_value, encoding="utf-8")
        return machine_value

    hostname = os.environ.get("COMPUTERNAME") or platform.node()
    if hostname:
        machine_value = f"host:{hostname}"
        machine_file.write_text(machine_value, encoding="utf-8")
        return machine_value

    machine_value = "unknown"
    machine_file.write_text(machine_value, encoding="utf-8")
    return machine_value


def get_salt() -> str:
    env_salt = os.getenv(SALT_ENV) or os.getenv("start-code-salt")
    if env_salt:
        SALT_PATH.write_text(env_salt, encoding="utf-8")
        return env_salt
    cached = _coerce_file(SALT_PATH, "salt")
    if cached:
        return cached
    salt = secrets.token_hex(16)
    SALT_PATH.write_text(salt, encoding="utf-8")
    return salt


def initialize_auth_files() -> None:
    for path in (MACHINE_ID_PATH, SALT_PATH, Path(".telegram_user_id")):
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    get_machine_id()
    get_salt()
    ensure_user_id_file()


def derive_start_code(machine_id: str, salt: str) -> str:
    seed = f"{machine_id}:{salt}".encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    num = int.from_bytes(digest, "big")
    chars = []
    for _ in range(CODE_LENGTH):
        num, idx = divmod(num, len(ALPHABET))
        chars.append(ALPHABET[idx])
    return "".join(chars)


def get_start_code() -> str:
    return derive_start_code(get_machine_id(), get_salt())
