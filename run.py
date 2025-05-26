import json
import subprocess
import os
import signal
import sys


def load_ports():
    with open(os.path.join("config", "port-config.json"), encoding="utf-8") as f:
        data = json.load(f)
    return data.get("frontend", 4200), data.get("backend", 8000)


def main():
    frontend_port, backend_port = load_ports()

    print(f"🚀 Запускаем Angular (порт {frontend_port})")
    print(f"🧠 Запускаем Backend (порт {backend_port})")
    print("-" * 50)

    processes = []

    try:
        # Angular
        frontend = subprocess.Popen(
            [
                "npx",
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
            shell=True,
        )
        processes.append(frontend)

        # Backend
        backend = subprocess.Popen(
            ["uvicorn", "main:app", "--port", str(backend_port)],
            cwd="backend",
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=True,
        )
        processes.append(backend)

        # Ждём завершения
        for p in processes:
            p.wait()

    except KeyboardInterrupt:
        print("\n🛑 Прерывание! Завершаем процессы...")
        for p in processes:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        print("✅ Все процессы завершены.")


if __name__ == "__main__":
    main()
