from __future__ import annotations

import platform
import subprocess


def collect() -> dict:
    system = platform.system().lower()
    if system == "linux":
        return _linux()
    if system == "windows":
        return _windows()
    return {"software": []}


def _linux() -> dict:
    # Debian/Ubuntu
    try:
        out = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Package}\t${Version}\n"],
            stderr=subprocess.DEVNULL, timeout=30, text=True,
        )
        software = []
        for line in out.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                software.append({"name": parts[0], "version": parts[1], "outdated": False})
        if software:
            return {"software": software}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # RHEL/CentOS/Fedora
    try:
        out = subprocess.check_output(
            ["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}-%{RELEASE}\n"],
            stderr=subprocess.DEVNULL, timeout=30, text=True,
        )
        software = []
        for line in out.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                software.append({"name": parts[0], "version": parts[1], "outdated": False})
        return {"software": software}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    return {"software": []}


def _windows() -> dict:
    ps_cmd = (
        "Get-ItemProperty "
        "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,"
        "HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
        "| Select-Object DisplayName,DisplayVersion "
        "| Where-Object { $_.DisplayName } "
        "| ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-Command", ps_cmd],
            stderr=subprocess.DEVNULL, timeout=30, text=True,
        )
        import json
        items = json.loads(out)
        if isinstance(items, dict):
            items = [items]
        software = []
        for item in items:
            name = item.get("DisplayName")
            if name:
                software.append({
                    "name": name,
                    "version": item.get("DisplayVersion") or "unknown",
                    "outdated": False,
                })
        return {"software": software}
    except Exception:
        pass

    return {"software": []}
