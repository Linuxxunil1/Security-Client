#!/usr/bin/env python3
"""Security Client — collects system security data and reports to Security Server."""
from __future__ import annotations

import logging
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv, set_key

_HERE = Path(__file__).parent
_ENV_FILE = _HERE / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)

SERVER_URL: str = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
CLIENT_NAME: str = os.environ.get("CLIENT_NAME", "") or platform.node()
API_KEY: str = os.environ.get("API_KEY", "")
CLIENT_ID: str = os.environ.get("CLIENT_ID", "")
SCAN_INTERVAL: int = int(os.environ.get("SCAN_INTERVAL", "300"))
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "30"))
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("security-client")

OS_TYPE = "windows" if platform.system().lower() == "windows" else "linux"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _persist(key: str, value: str) -> None:
    """Write key=value to .env and update os.environ."""
    if not _ENV_FILE.exists():
        _ENV_FILE.write_text("")
    set_key(str(_ENV_FILE), key, value)
    os.environ[key] = value


def _session() -> requests.Session:
    s = requests.Session()
    if API_KEY:
        s.headers["X-API-Key"] = API_KEY
    return s


# ---------------------------------------------------------------------------
# Server communication
# ---------------------------------------------------------------------------

def register() -> tuple[str, str]:
    """Register this client. Returns (client_id, api_key)."""
    resp = requests.post(
        f"{SERVER_URL}/api/clients",
        json={"name": CLIENT_NAME, "os_type": OS_TYPE},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data["api_key"]


def submit_scan(scan_type: str, raw_data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        resp = _session().post(
            f"{SERVER_URL}/api/scans",
            json={"scan_type": scan_type, "raw_data": raw_data},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.error("Scan submission failed (%s): %s", scan_type, exc)
        return None


def get_pending_commands() -> list[dict[str, Any]]:
    try:
        resp = _session().get(
            f"{SERVER_URL}/api/commands/{CLIENT_ID}/pending",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.error("Failed to fetch commands: %s", exc)
        return []


def report_command_result(
    command_id: str,
    status: str,
    result: dict[str, Any] | None = None,
) -> None:
    body: dict[str, Any] = {"status": status}
    if result is not None:
        body["result"] = result
    try:
        resp = _session().patch(
            f"{SERVER_URL}/api/commands/{command_id}/status",
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Failed to report command %s: %s", command_id, exc)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _load_scanners() -> dict[str, Any]:
    from scanners import (
        file_integrity,
        firewall_status,
        installed_software,
        network_connections,
        open_ports,
        running_processes,
        system_info,
        user_accounts,
    )
    return {
        "system_info": system_info.collect,
        "open_ports": open_ports.collect,
        "running_processes": running_processes.collect,
        "user_accounts": user_accounts.collect,
        "installed_software": installed_software.collect,
        "firewall_status": firewall_status.collect,
        "file_integrity": file_integrity.collect,
        "network_connections": network_connections.collect,
    }


def run_scan(scan_type: str | None = None) -> None:
    """Run one named scan or all scans and submit results to the server."""
    scanners = _load_scanners()
    targets = {scan_type: scanners[scan_type]} if (scan_type and scan_type in scanners) else scanners

    for name, collector in targets.items():
        try:
            log.debug("Running scanner: %s", name)
            raw = collector()
            result = submit_scan(name, raw)
            if result:
                log.info(
                    "%-25s  severity=%-8s  score=%d",
                    name,
                    result.get("severity", "?"),
                    result.get("score", 0),
                )
        except Exception as exc:
            log.error("Scanner %s raised an error: %s", name, exc)


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

def handle_command(cmd: dict[str, Any]) -> None:
    command_id: str = cmd["id"]
    command_type: str = cmd["command_type"]
    payload: dict[str, Any] = cmd.get("payload") or {}

    log.info("Executing command id=%s type=%s", command_id, command_type)

    try:
        if command_type == "run_scan":
            scan_type = payload.get("scan_type")
            run_scan(scan_type)
            report_command_result(
                command_id, "completed",
                {"output": f"scan '{scan_type or 'all'}' completed"},
            )

        elif command_type == "collect_info":
            run_scan()
            report_command_result(command_id, "completed", {"output": "full scan completed"})

        elif command_type == "execute_script":
            script = payload.get("script", "")
            timeout = int(payload.get("timeout", 60))
            if OS_TYPE == "windows":
                args = ["powershell", "-NonInteractive", "-Command", script]
            else:
                args = ["bash", "-c", script]
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            report_command_result(command_id, "completed", {
                "output": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
            })

        else:
            log.warning("Unknown command type: %s", command_type)
            report_command_result(
                command_id, "failed",
                {"output": f"unknown command type: {command_type}"},
            )

    except Exception as exc:
        log.error("Command %s failed: %s", command_id, exc)
        report_command_result(command_id, "failed", {"output": str(exc)})


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    global API_KEY, CLIENT_ID

    if not (API_KEY and CLIENT_ID):
        log.info("Registering '%s' (%s) with %s …", CLIENT_NAME, OS_TYPE, SERVER_URL)
        retries = 5
        for attempt in range(1, retries + 1):
            try:
                CLIENT_ID, API_KEY = register()
                _persist("CLIENT_ID", CLIENT_ID)
                _persist("API_KEY", API_KEY)
                log.info("Registration successful — client_id=%s", CLIENT_ID)
                break
            except Exception as exc:
                log.error("Registration attempt %d/%d failed: %s", attempt, retries, exc)
                if attempt == retries:
                    log.critical("Giving up after %d attempts.", retries)
                    sys.exit(1)
                time.sleep(10 * attempt)

    running = True

    def _stop(sig: int, _frame: Any) -> None:
        nonlocal running
        log.info("Shutdown requested (signal %d)", sig)
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info(
        "Client running — os=%s  scan_interval=%ds  poll_interval=%ds",
        OS_TYPE, SCAN_INTERVAL, POLL_INTERVAL,
    )

    last_scan = 0.0
    last_poll = 0.0

    while running:
        now = time.monotonic()

        if now - last_scan >= SCAN_INTERVAL:
            log.info("Starting scheduled scan cycle")
            run_scan()
            last_scan = now

        if now - last_poll >= POLL_INTERVAL:
            commands = get_pending_commands()
            for cmd in commands:
                handle_command(cmd)
            last_poll = now

        time.sleep(5)

    log.info("Client stopped.")


if __name__ == "__main__":
    main()
