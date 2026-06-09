from __future__ import annotations

import sys
import time
import platform

import psutil


def collect() -> dict:
    uname = platform.uname()
    uptime_days = (time.time() - psutil.boot_time()) / 86400

    return {
        "os_version": f"{uname.system} {uname.release}",
        "kernel": uname.release,
        "hostname": uname.node,
        "architecture": uname.machine,
        "uptime_days": round(uptime_days, 1),
        "cpu_count": psutil.cpu_count(logical=True),
        "total_memory_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
        "python_version": sys.version.split()[0],
    }
