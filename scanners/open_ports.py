from __future__ import annotations

import psutil


def collect() -> dict:
    ports: set[int] = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr:
                ports.add(conn.laddr.port)
    except psutil.AccessDenied:
        pass
    return {"ports": sorted(ports)}
