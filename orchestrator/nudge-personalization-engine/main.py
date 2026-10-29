"""
Root launcher for the Outreach Personalization Engine.

Starts all services in one command:
  - Temporal dev server (port 7233, UI on 8233)
  - Message Generator (port 8000)
  - Sequence Generator (port 8001)
  - Outreach Orchestrator (port 8002)
  - Temporal Worker (connects to local Temporal server)

Usage:
    python main.py
"""

import subprocess
import sys
import os
import time
import socket
import threading
from pathlib import Path


SERVICES = [
    {
        "name": "Message Generator",
        "directory": "message generator and sender",
        "module": "app.main",
        "port": 8000,
    },
    {
        "name": "Sequence Generator",
        "directory": "sequence generator",
        "module": "scripts.api_server",
        "port": 8001,
    },
    {
        "name": "Outreach Orchestrator",
        "directory": "outreach orchestrator",
        "module": "app.main",
        "port": 8002,
    },
    {
        "name": "Temporal Worker",
        "directory": "sequence generator",
        "script": "scripts/worker.py",  # run as a script, not a module
        "port": None,
    },
]

TEMPORAL_PORT = 7233
TEMPORAL_UI_PORT = 8233


def stream_output(name: str, process: subprocess.Popen):
    """Read stdout from a subprocess and print each line prefixed with the service name."""
    prefix = f"[{name}]"
    try:
        for line in iter(process.stdout.readline, ""):
            print(f"{prefix} {line}", end="", flush=True)
    except ValueError:
        pass  # pipe closed on termination


def wait_for_port(port: int, timeout: int = 30) -> bool:
    """Wait until a TCP port is accepting connections, or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def start_temporal_server() -> subprocess.Popen | None:
    """Start the Temporal dev server. Returns the process, or None if unavailable."""
    # Check if already running
    if wait_for_port(TEMPORAL_PORT, timeout=2):
        print(f"✓ Temporal Server already running on port {TEMPORAL_PORT}", flush=True)
        return None

    try:
        proc = subprocess.Popen(
            ["temporal", "server", "start-dev",
             "--port", str(TEMPORAL_PORT),
             "--ui-port", str(TEMPORAL_UI_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        t = threading.Thread(target=stream_output, args=("Temporal Server", proc), daemon=True)
        t.start()

        # Wait for it to accept connections
        if wait_for_port(TEMPORAL_PORT, timeout=30):
            print(f"✓ Temporal Server started on port {TEMPORAL_PORT} (UI: http://localhost:{TEMPORAL_UI_PORT})", flush=True)
            return proc
        else:
            print(f"⚠ Temporal Server did not start within 30s — skipping", flush=True)
            proc.terminate()
            return None
    except FileNotFoundError:
        print(f"⚠ Temporal CLI not found — install with: winget install temporalio.cli", flush=True)
        return None


def start_service(name: str, directory: str, port: int,
                  module: str = None, script: str = None) -> subprocess.Popen:
    """Start a uvicorn service or script using the venv python directly."""
    project_root = Path(__file__).parent
    svc_dir = project_root / directory

    if os.name == "nt":
        python = svc_dir / "venv" / "Scripts" / "python.exe"
    else:
        python = svc_dir / "venv" / "bin" / "python"

    if script:
        cmd = [str(python), str(svc_dir / script)]
    else:
        if port is None:
            raise ValueError(f"port is required for module-based service '{name}'")
        cmd = [str(python), "-m", "uvicorn", f"{module}:app",
               "--host", "0.0.0.0", "--port", str(port)]

    process = subprocess.Popen(
        cmd,
        cwd=str(svc_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    t = threading.Thread(target=stream_output, args=(name, process), daemon=True)
    t.start()

    return process


def main():
    processes = []

    try:
        # Start Temporal dev server first (worker depends on it)
        temporal_proc = start_temporal_server()
        if temporal_proc:
            processes.append(("Temporal Server", temporal_proc))

        for svc in SERVICES:
            proc = start_service(
                name=svc["name"],
                directory=svc["directory"],
                port=svc.get("port"),
                module=svc.get("module"),
                script=svc.get("script"),
            )
            processes.append((svc["name"], proc))
            port_str = f"on port {svc['port']}" if svc.get("port") else "(no port)"
            print(f"✓ {svc['name']} started {port_str} (PID: {proc.pid})", flush=True)

        print("\n" + "=" * 60)
        print("All services running. Press Ctrl+C to stop all.")
        print("=" * 60 + "\n", flush=True)

        # Watch for unexpected exits
        while True:
            time.sleep(1)
            for name, proc in list(processes):
                if proc.poll() is not None:
                    print(f"\n⚠  {name} stopped unexpectedly (exit code: {proc.returncode})", flush=True)
                    processes.remove((name, proc))
            if not processes:
                print("All services have stopped.", flush=True)
                break

    except KeyboardInterrupt:
        print("\n\nStopping all services...", flush=True)
        for name, proc in processes:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"✓ {name} stopped", flush=True)

    except Exception as e:
        print(f"\nError: {e}", flush=True)
        for _, proc in processes:
            proc.terminate()
        sys.exit(1)


if __name__ == "__main__":
    main()
