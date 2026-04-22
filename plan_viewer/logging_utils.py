from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _default_log_path() -> Path:
    return Path(__file__).resolve().parent.parent / "training_data.jsonl"


def log_event(payload: dict, log_path: Path | None = None) -> None:
    payload = dict(payload)
    payload["ts"] = datetime.now().isoformat(timespec="seconds")
    path = log_path or _default_log_path()
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
