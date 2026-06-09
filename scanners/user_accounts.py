from __future__ import annotations

import platform
import subprocess


def collect() -> dict:
    system = platform.system().lower()
    if system == "linux":
        return _linux()
    if system == "windows":
        return _windows()
    return {"accounts": []}


def _linux() -> dict:
    interactive_shells = {"/bin/bash", "/bin/sh", "/bin/zsh", "/bin/fish", "/bin/dash"}
    accounts = []

    try:
        with open("/etc/passwd") as fh:
            for line in fh:
                parts = line.strip().split(":")
                if len(parts) < 7:
                    continue
                name, _, uid_str, _, _, _, shell = parts[:7]
                if shell not in interactive_shells:
                    continue
                try:
                    uid = int(uid_str)
                except ValueError:
                    uid = -1
                accounts.append({"name": name, "uid": uid, "no_password": False, "sudo": False})
    except OSError:
        pass

    # Check passwordless accounts (requires root)
    try:
        with open("/etc/shadow") as fh:
            shadow = {}
            for line in fh:
                parts = line.split(":")
                if len(parts) >= 2:
                    shadow[parts[0]] = parts[1]
        for acc in accounts:
            pw = shadow.get(acc["name"], "x")
            if pw in ("", "!", "*", "!!"):
                acc["no_password"] = True
    except (OSError, PermissionError):
        pass

    # Check sudo/wheel/admin group membership
    for group in ("sudo", "wheel", "admin"):
        try:
            out = subprocess.check_output(
                ["getent", "group", group], stderr=subprocess.DEVNULL, timeout=5, text=True
            )
            members = out.strip().split(":")[-1].split(",")
            for acc in accounts:
                if acc["name"] in members:
                    acc["sudo"] = True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    return {"accounts": accounts}


def _windows() -> dict:
    accounts = []

    try:
        out = subprocess.check_output(
            ["powershell", "-Command",
             "Get-LocalUser | Select-Object Name,Enabled,PasswordRequired | ConvertTo-Json"],
            stderr=subprocess.DEVNULL, timeout=15, text=True,
        )
        import json
        items = json.loads(out)
        if isinstance(items, dict):
            items = [items]
        for item in items:
            accounts.append({
                "name": item.get("Name", ""),
                "uid": None,
                "no_password": not item.get("PasswordRequired", True),
                "sudo": False,
            })
    except Exception:
        try:
            out = subprocess.check_output(
                ["net", "user"], stderr=subprocess.DEVNULL, timeout=10, text=True
            )
            for line in out.splitlines()[4:]:
                for name in line.split():
                    if name and name not in ("The", "command", "completed", "successfully."):
                        accounts.append({"name": name, "uid": None, "no_password": False, "sudo": False})
        except Exception:
            pass

    try:
        out = subprocess.check_output(
            ["net", "localgroup", "Administrators"],
            stderr=subprocess.DEVNULL, timeout=10, text=True,
        )
        admin_names = {
            l.strip() for l in out.splitlines()[6:]
            if l.strip() and l.strip() != "The command completed successfully."
        }
        for acc in accounts:
            if acc["name"] in admin_names:
                acc["sudo"] = True
    except Exception:
        pass

    return {"accounts": accounts}
