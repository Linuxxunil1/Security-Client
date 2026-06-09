from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path


_LINUX_PATHS = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/hosts",
    "/etc/ssh/sshd_config",
    "/etc/crontab",
    "/etc/fstab",
    "/etc/resolv.conf",
]

_WINDOWS_PATHS = [
    r"C:\Windows\System32\drivers\etc\hosts",
    r"C:\Windows\System32\config\SAM",
]

_STATE_FILE = Path(__file__).parent.parent / "data" / "file_integrity.json"


def _hash_file(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def collect() -> dict:
    system = platform.system().lower()
    monitored = _LINUX_PATHS if system == "linux" else _WINDOWS_PATHS

    current: dict[str, str] = {}
    for path in monitored:
        digest = _hash_file(path)
        if digest is not None:
            current[path] = digest

    changed: list[dict] = []
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _STATE_FILE.exists():
        try:
            previous: dict[str, str] = json.loads(_STATE_FILE.read_text())
            for path, prev_hash in previous.items():
                if path not in current:
                    changed.append({"path": path, "change": "deleted"})
                elif current[path] != prev_hash:
                    changed.append({"path": path, "change": "modified"})
            for path in current:
                if path not in previous:
                    changed.append({"path": path, "change": "added"})
        except (json.JSONDecodeError, OSError):
            pass

    _STATE_FILE.write_text(json.dumps(current, indent=2))
    return {"changed_files": changed}
