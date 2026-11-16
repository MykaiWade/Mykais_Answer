"""Start the website and its Cloudflare Tunnel. Stop both with Ctrl+C."""

import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SERVER_FILE = ROOT / "server.py"
TUNNEL_ID = "4164dfc1-5873-4ee6-84d6-d68af4a5b9be"
ORIGIN_URL = "http://127.0.0.1:8000"
TUNNEL_CREDENTIALS = Path.home() / ".cloudflared" / f"{TUNNEL_ID}.json"


def find_cloudflared():
    executable = shutil.which("cloudflared")
    if executable:
        return executable

    windows_executable = Path(
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    )
    if windows_executable.is_file():
        return str(windows_executable)

    raise FileNotFoundError(
        "cloudflared was not found. Install Cloudflare Tunnel before starting."
    )


def ensure_port_is_free():
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            raise RuntimeError(
                "Port 8000 is already in use or unavailable. Stop the existing "
                "website server before running startup.py."
            ) from None


def wait_for_website(server_process, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_process.poll() is not None:
            raise RuntimeError(
                f"The website server exited with code {server_process.returncode}."
            )
        try:
            with urllib.request.urlopen(ORIGIN_URL, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)

    raise RuntimeError(f"The website did not start at {ORIGIN_URL} within {timeout} seconds.")


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    if not SERVER_FILE.is_file():
        raise FileNotFoundError(f"Website server not found: {SERVER_FILE}")
    if not TUNNEL_CREDENTIALS.is_file():
        raise FileNotFoundError(
            f"Cloudflare Tunnel credentials not found: {TUNNEL_CREDENTIALS}"
        )
    cloudflared = find_cloudflared()
    ensure_port_is_free()

    server_process = None
    tunnel_process = None
    try:
        print("Starting the website...", flush=True)
        server_process = subprocess.Popen(
            [sys.executable, str(SERVER_FILE)],
            cwd=str(ROOT),
        )
        wait_for_website(server_process)
        print("Website is responding at http://127.0.0.1:8000", flush=True)

        print("Starting the Cloudflare Tunnel...", flush=True)
        tunnel_process = subprocess.Popen(
            [
                cloudflared,
                "tunnel",
                "--credentials-file",
                str(TUNNEL_CREDENTIALS),
                "run",
                "--url",
                ORIGIN_URL,
                TUNNEL_ID,
            ],
            cwd=str(ROOT),
        )
        time.sleep(2)
        if tunnel_process.poll() is not None:
            raise RuntimeError(
                f"Cloudflare Tunnel exited with code {tunnel_process.returncode}."
            )

        print("Website is online at https://mykaianswer.com", flush=True)
        print("Keep this window open. Press Ctrl+C to stop the website and tunnel.", flush=True)

        while True:
            if server_process.poll() is not None:
                raise RuntimeError(
                    f"The website server exited with code {server_process.returncode}."
                )
            if tunnel_process.poll() is not None:
                raise RuntimeError(
                    f"Cloudflare Tunnel exited with code {tunnel_process.returncode}."
                )
            time.sleep(1)
    finally:
        stop_process(tunnel_process)
        stop_process(server_process)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopping the website and Cloudflare Tunnel.", flush=True)
    except (FileNotFoundError, RuntimeError) as error:
        print(f"Startup failed: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
