from pathlib import Path

from app.start_code import (
    ALPHABET,
    CODE_LENGTH,
    ensure_start_code_present,
    get_start_code,
    initialize_auth_files,
)


def test_get_start_code_persists(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    code = get_start_code()
    assert len(code) == CODE_LENGTH
    assert all(char in ALPHABET for char in code)
    code_path = Path(".telegram_start_code")
    assert code_path.exists()
    assert code_path.read_text(encoding="utf-8").strip() == code
    assert get_start_code() == code


def test_initialize_auth_files_creates_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    initialize_auth_files()
    assert Path(".telegram_start_code").exists()
    assert Path(".telegram_user_id").exists()


def test_ensure_start_code_present_creates_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    code = ensure_start_code_present()
    assert len(code) == CODE_LENGTH
    assert all(char in ALPHABET for char in code)
    code_path = Path(".telegram_start_code")
    assert code_path.exists()
    assert code_path.read_text(encoding="utf-8").strip() == code
