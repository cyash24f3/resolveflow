"""Supervise the API and separate worker process on a single free web instance.

Business state stays in external PostgreSQL. A sleeping host does no work;
existing job leases and operation identities govern recovery when it returns.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time

from resolveflow.settings import get_settings


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


def terminate(processes, grace_seconds=125):
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + grace_seconds
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()


def serve(port, stop, startup_seconds=120):
    processes = []
    try:
        # Migration failures can contain database URLs. Keep those details out of
        # public host logs; publish only the stage and exit code here.
        migration = subprocess.Popen(
            [sys.executable, "-m", "resolveflow.cli", "init"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        processes.append(migration)
        deadline = time.monotonic() + startup_seconds
        while migration.poll() is None:
            if stop.wait(0.2):
                return 0
            if time.monotonic() >= deadline:
                emit("host_startup_timeout")
                return 1
        if migration.returncode != 0:
            emit("host_initialization_failed", exit_code=migration.returncode)
            return 1
        if stop.is_set():
            return 0
        commands = [
            ("worker", [sys.executable, "-m", "resolveflow.jobs.worker"]),
            (
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "resolveflow.api.app:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(port),
                    "--no-access-log",
                    "--no-proxy-headers",
                ],
            ),
        ]
        children = []
        for name, command in commands:
            child = subprocess.Popen(command, start_new_session=True)
            processes.append(child)
            children.append((name, child))
        emit("host_started", port=port, worker_process="separate", simulated=True)
        while not stop.wait(0.2):
            for name, child in children:
                if child.poll() is not None:
                    emit("host_child_exited", child=name, exit_code=child.returncode)
                    # Even a clean unexpected worker exit must trigger a host
                    # restart rather than leaving a healthy API and stuck queue.
                    return 1
        emit("host_stopping")
        return 0
    finally:
        terminate(processes)


def main():
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        cfg = get_settings()
        if cfg.demo_mode or not cfg.cookie_secure:
            raise ValueError("Hosted runtime requires credentials and secure cookies")
        port = int(os.environ.get("PORT", "10000"))
        if not 1024 <= port <= 65535:
            raise ValueError("Invalid listening port")
    except Exception as exc:
        emit("host_configuration_invalid", error_type=type(exc).__name__)
        raise SystemExit(1) from None
    try:
        raise SystemExit(serve(port, stop))
    except OSError as exc:
        emit("host_process_error", error_type=type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
