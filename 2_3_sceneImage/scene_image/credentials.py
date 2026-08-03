# -*- coding: utf-8 -*-
"""Genspark 로그인 계정 — dist 로컬 JSON (소스·커밋에 비밀번호 넣지 않음)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CRED_NAME = "scene_image_credentials.json"


def credentials_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CRED_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CRED_NAME


def load_credentials() -> tuple[str, str]:
    """(email, password). 환경변수 SCENE_IMAGE_EMAIL / SCENE_IMAGE_PASSWORD 우선."""
    email = os.environ.get("SCENE_IMAGE_EMAIL", "").strip()
    password = os.environ.get("SCENE_IMAGE_PASSWORD", "").strip()
    if email and password:
        return email, password
    p = credentials_path()
    if not p.is_file():
        return "", ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    e = str(data.get("email") or data.get("id") or "").strip()
    pw = str(data.get("password") or data.get("pw") or "").strip()
    return e, pw


def save_credentials(email: str, password: str) -> None:
    p = credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"email": email.strip(), "password": password},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
