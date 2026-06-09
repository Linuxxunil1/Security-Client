from __future__ import annotations

import psutil


def collect() -> dict:
    connections = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            connections.append({
                "local_port": conn.laddr.port if conn.laddr else None,
                "local_address": conn.laddr.ip if conn.laddr else None,
                "remote_address": (
                    f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else None
                ),
                "state": conn.status,
                "pid": conn.pid,
            })
    except psutil.AccessDenied:
        pass
    return {"connections": connections}
