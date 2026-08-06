#!/usr/bin/env python3
"""ARIA NEXUS v2 environment doctor.

Stdlib-only diagnostics for the Windows laptop profile. This script does not
install software, download models, expose secrets, or change system settings.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    name: str
    status: str
    detail: str
    critical: bool = False


checks: list[Check] = []


def add(name: str, status: str, detail: str, critical: bool = False) -> None:
    checks.append(Check(name, status, detail, critical))


def run(command: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        output = (completed.stdout or completed.stderr or "").strip()
        return completed.returncode, output
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def check_platform() -> None:
    is_windows = os.name == "nt"
    add(
        "Operating system",
        "PASS" if is_windows else "WARN",
        f"{platform.system()} {platform.release()} ({platform.machine()})",
        critical=False,
    )
    version = platform.python_version()
    supported = sys.version_info[:2] == (3, 12)
    add(
        "Python",
        "PASS" if supported else "FAIL",
        f"{version} at {sys.executable}; Python 3.12 is required for this profile",
        critical=True,
    )


def check_repo() -> None:
    required = [
        "backend/server.py",
        "backend/config.py",
        "backend/test_smoke.py",
        "frontend/application/nexus_app.html",
        "AGENTS.md",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    add(
        "Repository layout",
        "FAIL" if missing else "PASS",
        "Missing: " + ", ".join(missing) if missing else str(ROOT),
        critical=True,
    )

    if shutil.which("git"):
        code, branch = run(["git", "branch", "--show-current"])
        branch = branch.strip() if code == 0 else "unknown"
        add(
            "Git branch",
            "PASS" if branch == "v2-windows" else "WARN",
            branch or "detached/unknown",
        )
    else:
        add("Git branch", "FAIL", "git is not available", critical=True)


def check_commands() -> None:
    commands = {
        "git": True,
        "ffmpeg": True,
        "cmake": False,
        "ninja": False,
        "nvidia-smi": True,
    }
    for command, critical in commands.items():
        found = shutil.which(command)
        add(
            f"Command: {command}",
            "PASS" if found else ("FAIL" if critical else "WARN"),
            found or "not found in PATH",
            critical=critical,
        )


def check_gpu() -> None:
    if not shutil.which("nvidia-smi"):
        return
    code, output = run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.free",
            "--format=csv,noheader",
        ]
    )
    add(
        "NVIDIA GPU",
        "PASS" if code == 0 else "FAIL",
        output.splitlines()[0] if output else "query failed",
        critical=True,
    )


def check_python_packages() -> None:
    core = [
        "flask",
        "flask_cors",
        "flask_socketio",
        "requests",
        "OpenSSL",
        "numpy",
        "psutil",
        "yaml",
    ]
    optional = [
        "langchain_community",
        "chromadb",
        "sentence_transformers",
        "piper",
        "openwakeword",
        "sounddevice",
    ]

    missing_core = [name for name in core if importlib.util.find_spec(name) is None]
    add(
        "Core Python packages",
        "FAIL" if missing_core else "PASS",
        "Missing: " + ", ".join(missing_core) if missing_core else "all installed",
        critical=True,
    )

    missing_optional = [
        name for name in optional if importlib.util.find_spec(name) is None
    ]
    add(
        "Optional AI packages",
        "WARN" if missing_optional else "PASS",
        "Not installed yet: " + ", ".join(missing_optional)
        if missing_optional
        else "all installed",
    )


def check_config_urls() -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        import config  # type: ignore
    except Exception as exc:
        add("Local service URLs", "FAIL", f"config import failed: {exc}", True)
        return

    problems: list[str] = []
    rendered: list[str] = []
    for name in ("WHISPER_URL", "LLAMA_URL", "TTS_URL"):
        value = str(getattr(config, name, ""))
        parsed = urlparse(value)
        rendered.append(f"{name}={value}")
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or "{" in value
            or "}" in value
        ):
            problems.append(name)

    add(
        "Local service URLs",
        "FAIL" if problems else "PASS",
        "Invalid: " + ", ".join(problems) if problems else "; ".join(rendered),
        critical=True,
    )


def check_ports() -> None:
    busy: list[str] = []
    for port in (5000, 5002, 8080, 8081):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(str(port))
    add(
        "ARIA ports",
        "WARN" if busy else "PASS",
        "Busy: " + ", ".join(busy) if busy else "5000, 5002, 8080, 8081 are free",
    )


def check_runtime_assets() -> None:
    assets = {
        "LLM binary": ROOT / "vendor/llama.cpp/build/bin/llama-server.exe",
        "Whisper binary": ROOT
        / "vendor/whisper.cpp/build/bin/Release/whisper-server.exe",
        "LLM model": ROOT / "models/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "Whisper model": ROOT / "models/ggml-large-v3-turbo.bin",
    }
    missing = [name for name, path in assets.items() if not path.exists()]
    add(
        "Runtime assets",
        "WARN" if missing else "PASS",
        "Not installed yet: " + ", ".join(missing) if missing else "available",
    )


def check_disk() -> None:
    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / (1024**3)
    add(
        "Free disk space",
        "PASS" if free_gb >= 40 else "WARN",
        f"{free_gb:.1f} GB free on {ROOT.drive or ROOT.anchor}",
    )


def render_text() -> str:
    widths = {"name": 26, "status": 6}
    lines = [
        "=" * 88,
        "ARIA NEXUS v2 - WINDOWS PROJECT DOCTOR",
        f"Repository: {ROOT}",
        "=" * 88,
    ]
    for item in checks:
        lines.append(
            f"{item.status:<{widths['status']}}  {item.name:<{widths['name']}}  {item.detail}"
        )
    critical_failures = [c for c in checks if c.critical and c.status == "FAIL"]
    lines.extend(
        [
            "=" * 88,
            f"Critical failures: {len(critical_failures)}",
            "Warnings are expected until models and optional AI packages are installed.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON output")
    parser.add_argument(
        "--save",
        type=Path,
        help="save the report to this path in addition to printing it",
    )
    args = parser.parse_args()

    check_platform()
    check_repo()
    check_commands()
    check_gpu()
    check_python_packages()
    check_config_urls()
    check_ports()
    check_runtime_assets()
    check_disk()

    if args.json:
        output = json.dumps(
            {
                "repository": str(ROOT),
                "checks": [asdict(item) for item in checks],
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        output = render_text()

    print(output)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(output + "\n", encoding="utf-8")
        print(f"Saved report: {args.save}")

    return 1 if any(c.critical and c.status == "FAIL" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
