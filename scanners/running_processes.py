from __future__ import annotations

import psutil


def collect() -> dict:
    processes = []
    for proc in psutil.process_iter(["name", "pid", "username"]):
        try:
            processes.append({
                "name": proc.info["name"] or "",
                "pid": proc.info["pid"],
                "username": proc.info.get("username") or "",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {"processes": processes}
