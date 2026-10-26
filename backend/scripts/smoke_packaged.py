"""Start the packaged backend program and check that it really works.

Usage:  python scripts/smoke_packaged.py dist/backend      (dist/backend.exe on Windows)

The normal tests run the backend with plain Python, so they cannot catch
problems that only appear after packaging (a missing or mismatched library).
This script runs the packaged file the same way the desktop app does and
asks for real market lists from the exchange.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def get(path: str):
    try:
        with urllib.request.urlopen(BASE + path, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def main(program: str) -> int:
    env = dict(os.environ, EXIT_WHEN_PARENT_CLOSES="1")
    # Same as the desktop app: input pipe open, output read.
    process = subprocess.Popen([program], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=env)
    failed = False
    try:
        for _ in range(90):
            if process.poll() is not None:
                print("::error title=Packaged backend::program exited during start-up")
                failed = True
                break
            try:
                status, _ = get("/api/health")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            print("::error title=Packaged backend::no answer after 90 seconds")
            failed = True

        if not failed:
            for market_type in ("spot", "futures"):
                status, body = get(f"/api/markets?market_type={market_type}")
                count = len(body.get("markets", []))
                print(f"{market_type}: HTTP {status}, {count} markets")
                if status != 200 or count == 0:
                    detail = str(body.get("detail", body))[:800]
                    print(f"::error title=Packaged backend {market_type}::HTTP {status}: {detail}")
                    failed = True
    finally:
        process.stdin.close()  # the "app" closes: the backend should exit by itself
        try:
            process.wait(timeout=15)
            print("backend exited after its input closed")
        except subprocess.TimeoutExpired:
            print("::error title=Packaged backend::did not exit when its input closed")
            process.kill()
            failed = True
        output = process.stdout.read().decode(errors="replace")
        if output.strip():
            print("---- backend output ----")
            print(output[-4000:])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
