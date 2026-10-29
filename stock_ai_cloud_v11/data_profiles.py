"""Per-user/profile data separation for the stock research app.

The app-level mobile PIN controls access to the LAN app. Profiles only separate
watchlist/portfolio files; they are not security accounts and do not replace the
mobile access PIN.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from pathlib import Path

_REGISTRY_NAME = "profiles.json"
_LOCK = threading.Lock()
_ID_RE = re.compile(r"(?:pc|iphone|p_[0-9a-f]{12})\Z")
_BUILTINS = (
    {"id": "pc", "name": "PC 기본 데이터", "builtin": True},
    {"id": "iphone", "name": "iPhone 전용 데이터", "builtin": True},
)


def profile_directory(root: Path, profile_id: str) -> Path:
    root = Path(root).expanduser().resolve()
    if not isinstance(profile_id, str) or not _ID_RE.fullmatch(profile_id):
        raise ValueError("데이터 프로필 식별자가 올바르지 않습니다.")
    if profile_id == "pc":
        # Backward compatibility: existing desktop data stays in the original root.
        return root
    return root / "profiles" / profile_id


def _normalize_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("프로필 이름을 입력해 주세요.")
    value = " ".join(name.strip().split())
    if not value:
        raise ValueError("프로필 이름을 입력해 주세요.")
    if len(value) > 30:
        raise ValueError("프로필 이름은 30자 이내로 입력해 주세요.")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("프로필 이름에 제어 문자를 사용할 수 없습니다.")
    return value


def _read_registry(root: Path) -> list[dict]:
    path = Path(root) / _REGISTRY_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return []
    result = []
    for row in raw.get("profiles", []):
        if not isinstance(row, dict):
            continue
        profile_id = row.get("id")
        name = row.get("name")
        if not isinstance(profile_id, str) or not profile_id.startswith("p_") or not _ID_RE.fullmatch(profile_id):
            continue
        try:
            clean_name = _normalize_name(name)
        except ValueError:
            continue
        result.append({"id": profile_id, "name": clean_name, "builtin": False})
    return result[:20]


def list_profiles(root: Path) -> list[dict]:
    """Return built-ins first, then custom profiles."""
    root = Path(root).expanduser().resolve()
    custom = _read_registry(root)
    seen = {row["id"] for row in _BUILTINS}
    result = [dict(row) for row in _BUILTINS]
    for row in custom:
        if row["id"] not in seen:
            result.append(row)
            seen.add(row["id"])
    return result


def _write_registry(root: Path, custom: list[dict]) -> None:
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / _REGISTRY_NAME
    payload = {"schema_version": 1, "profiles": [{"id": p["id"], "name": p["name"]} for p in custom]}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root, prefix=".profiles-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def create_profile(root: Path, name: str) -> dict:
    """Create a separate data profile and return its descriptor."""
    clean_name = _normalize_name(name)
    root = Path(root).expanduser().resolve()
    with _LOCK:
        existing = list_profiles(root)
        if any(row["name"].casefold() == clean_name.casefold() for row in existing):
            raise ValueError("같은 이름의 데이터 프로필이 이미 있습니다.")
        custom = [row for row in existing if not row.get("builtin")]
        if len(custom) >= 20:
            raise ValueError("사용자 프로필은 최대 20개까지 만들 수 있습니다.")
        profile_id = "p_" + secrets.token_hex(6)
        while any(row["id"] == profile_id for row in existing):
            profile_id = "p_" + secrets.token_hex(6)
        row = {"id": profile_id, "name": clean_name, "builtin": False}
        custom.append(row)
        _write_registry(root, custom)
        profile_directory(root, profile_id).mkdir(parents=True, exist_ok=True)
        return row


def ensure_profile_directory(root: Path, profile_id: str) -> Path:
    path = profile_directory(root, profile_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
