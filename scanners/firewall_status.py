from __future__ import annotations

import platform
import subprocess


def collect() -> dict:
    system = platform.system().lower()
    if system == "linux":
        return _linux()
    if system == "windows":
        return _windows()
    return {"enabled": None, "status": "unknown"}


def _linux() -> dict:
    # ufw
    try:
        out = subprocess.check_output(
            ["ufw", "status"], stderr=subprocess.DEVNULL, timeout=5, text=True
        )
        enabled = "active" in out.lower()
        rules = [l for l in out.splitlines() if l.strip() and not l.startswith("Status")]
        return {"enabled": enabled, "status": "active" if enabled else "inactive", "rules_count": len(rules)}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # firewalld
    try:
        out = subprocess.check_output(
            ["firewall-cmd", "--state"], stderr=subprocess.DEVNULL, timeout=5, text=True
        )
        enabled = "running" in out.lower()
        return {"enabled": enabled, "status": out.strip()}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # iptables
    try:
        out = subprocess.check_output(
            ["iptables", "-L", "--line-numbers"], stderr=subprocess.DEVNULL, timeout=5, text=True
        )
        rules = [
            l for l in out.splitlines()
            if l and not l.startswith("Chain") and not l.startswith("target")
        ]
        return {"enabled": True, "status": "iptables", "rules_count": len(rules)}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    return {"enabled": None, "status": "unknown"}


def _windows() -> dict:
    try:
        out = subprocess.check_output(
            ["netsh", "advfirewall", "show", "allprofiles"],
            stderr=subprocess.DEVNULL, timeout=10, text=True,
        )
        enabled = "on" in out.lower()
        return {"enabled": enabled, "status": "on" if enabled else "off"}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    try:
        out = subprocess.check_output(
            ["powershell", "-Command",
             "Get-NetFirewallProfile | Select-Object -ExpandProperty Enabled"],
            stderr=subprocess.DEVNULL, timeout=10, text=True,
        )
        enabled = "true" in out.lower()
        return {"enabled": enabled, "status": "on" if enabled else "off"}
    except Exception:
        pass

    return {"enabled": None, "status": "unknown"}
