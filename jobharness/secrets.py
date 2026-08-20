from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*a, **k):
        return False


def load_env(project_root: Optional[Path] = None) -> None:
    root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")


def get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


def proxy_list() -> list[str]:
    raw = get("PROXY_LIST", "")
    return [p.strip() for p in raw.split(",") if p.strip()]
