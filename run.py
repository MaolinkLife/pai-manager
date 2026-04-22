import json
import subprocess
import os
import signal
import sys
import time
import urllib.request
import urllib.error


sys.dont_write_bytecode = True
IS_WINDOWS = os.name == "nt"


def load_ports():
    with open(os.path.join("config", "port-config.json"), encoding="utf-8") as f:
        data = json.load(f)
    return data.get("frontend", 4200), data.get("backend", 8000)


def sync_frontend_proxy_target(backend_port: int) -> None:
    proxy_path = os.path.join("frontend", "proxy.conf.json")
    if not os.path.exists(proxy_path):
        return
    try:
        with open(proxy_path, "r", encoding="utf-8") as file:
            proxy_cfg = json.load(file)
        api_cfg = proxy_cfg.get("/api", {})
        if not isinstance(api_cfg, dict):
            return
        desired_target = f"http://127.0.0.1:{backend_port}"
        if api_cfg.get("target") == desired_target:
            return
        api_cfg["target"] = desired_target
        proxy_cfg["/api"] = api_cfg
        with open(proxy_path, "w", encoding="utf-8") as file:
            json.dump(proxy_cfg, file, ensure_ascii=False, indent=4)
            file.write("\n")
        print(f"Proxy target updated: {desired_target}")
    except Exception as exc:
        print(f"Warning: failed to sync proxy target: {exc}")


def wait_backend_ready(
    backend_process: subprocess.Popen, backend_port: int, timeout_sec: int = 120
) -> bool:
    deadline = time.time() + timeout_sec
    ping_url = f"http://127.0.0.1:{backend_port}/api/ping"
    stable_hits = 0

    while time.time() < deadline:
        if backend_process.poll() is not None:
            print(
                f"Backend process exited early with code {backend_process.returncode}."
            )
            return False
        try:
            with urllib.request.urlopen(ping_url, timeout=1.5) as response:
                if response.status == 200:
                    stable_hits += 1
                    if stable_hits >= 3:
                        return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            stable_hits = 0
        time.sleep(0.5)
    return False


def _popen_creationflags() -> int:
    if not IS_WINDOWS:
        return 0
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def stop_process(process: subprocess.Popen, *, label: str, timeout_sec: float = 8.0) -> None:
    if process.poll() is not None:
        return

    try:
        if IS_WINDOWS:
            ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
            if ctrl_break is not None:
                try:
                    process.send_signal(ctrl_break)
                except Exception:
                    process.terminate()
            else:
                process.terminate()
        else:
            process.send_signal(signal.SIGINT)
    except Exception as exc:
        print(f"Warning: failed to signal {label}: {exc}. Trying terminate().")
        try:
            process.terminate()
        except Exception as terminate_exc:
            print(f"Warning: failed to terminate {label}: {terminate_exc}.")

    try:
        process.wait(timeout=timeout_sec)
        return
    except subprocess.TimeoutExpired:
        print(f"{label} did not stop in time. Killing...")
        try:
            process.kill()
            process.wait(timeout=3.0)
        except Exception as kill_exc:
            print(f"Warning: failed to kill {label}: {kill_exc}")


def main():
    frontend_port, backend_port = load_ports()
    sync_frontend_proxy_target(backend_port)

    print(f"Start Frontend (port {frontend_port})")
    print(f"Start Backend (port {backend_port})")
    print("-" * 50)

    processes = []

    try:
        # Backend first
        backend = subprocess.Popen(
            ["uvicorn", "main:app", "--port", str(backend_port)],
            cwd="backend",
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=False,
            creationflags=_popen_creationflags(),
        )
        processes.append(backend)

        print(f"Waiting backend readiness: http://127.0.0.1:{backend_port}/api/ping")
        ready = wait_backend_ready(backend, backend_port, timeout_sec=120)
        if not ready:
            print(
                f"Backend did not become ready within timeout on port {backend_port}. "
                "Frontend start is cancelled."
            )
            stop_process(backend, label="Backend")
            return

        print("Backend is ready. Starting frontend...")
        # Angular
        frontend = subprocess.Popen(
            [
                "npx.cmd",
                "ng",
                "serve",
                "--port",
                str(frontend_port),
                "--proxy-config",
                "proxy.conf.json",
            ],
            cwd="frontend",
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=False,
            creationflags=_popen_creationflags(),
        )
        processes.append(frontend)

        # Waiting for completion
        for p in processes:
            p.wait()

    except KeyboardInterrupt:
        print("\nInterrupt! Terminating processes...")
        for index, p in enumerate(processes):
            if p.poll() is None:
                label = "Backend" if index == 0 else f"Process #{index + 1}"
                stop_process(p, label=label)
        print("All processes are completed.")


if __name__ == "__main__":
    main()
