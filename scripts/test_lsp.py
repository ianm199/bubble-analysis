"""Minimal LSP client that tests the bubble-lsp server over stdio.

Spawns the server as a subprocess, sends initialize + hover, prints responses.
No dependencies beyond the standard library.

Usage:
    python scripts/test_lsp.py
    .venv/bin/python scripts/test_lsp.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def make_request(method: str, params: dict, request_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def make_notification(method: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def encode_message(obj: dict) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def read_response(proc: subprocess.Popen) -> dict:
    """Read one LSP message from the server's stdout."""
    assert proc.stdout is not None
    headers: dict[str, str] = {}
    while True:
        line = proc.stdout.readline().decode("ascii")
        if line == "\r\n":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    content_length = int(headers["Content-Length"])
    body = proc.stdout.read(content_length)
    return json.loads(body)


def find_python(project_root: Path) -> str:
    """Find the best Python interpreter — prefer the project venv."""
    venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return sys.executable


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    python = find_python(project_root)

    print(f"Starting bubble-lsp server with {python}...")
    proc = subprocess.Popen(
        [python, "-m", "bubble.lsp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(project_root),
    )
    assert proc.stdin is not None

    try:
        print("Sending initialize...")
        init_request = make_request(
            "initialize",
            {
                "processId": None,
                "capabilities": {},
                "rootUri": project_root.as_uri(),
            },
            request_id=1,
        )
        proc.stdin.write(encode_message(init_request))
        proc.stdin.flush()

        init_response = read_response(proc)
        print(f"Server name: {init_response['result']['serverInfo']['name']}")
        print(f"Capabilities: {list(init_response['result']['capabilities'].keys())}")

        proc.stdin.write(encode_message(make_notification("initialized", {})))
        proc.stdin.flush()

        test_file = project_root / "bubble" / "cli.py"
        test_uri = test_file.as_uri()
        test_content = test_file.read_text()

        print(f"\nOpening {test_file.name}...")
        did_open = make_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": test_uri,
                    "languageId": "python",
                    "version": 1,
                    "text": test_content,
                },
            },
        )
        proc.stdin.write(encode_message(did_open))
        proc.stdin.flush()

        hover_line = 175
        print(f"Sending hover at line {hover_line + 1} (inside escapes function)...")
        hover_request = make_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": test_uri},
                "position": {"line": hover_line, "character": 0},
            },
            request_id=2,
        )
        proc.stdin.write(encode_message(hover_request))
        proc.stdin.flush()

        hover_response = read_response(proc)
        if "result" in hover_response and hover_response["result"]:
            content = hover_response["result"]["contents"]["value"]
            print(f"\nHover response:\n{content}")
            print("\n--- SUCCESS: LSP server is working ---")
        else:
            print(f"\nUnexpected response: {json.dumps(hover_response, indent=2)}")
            print("\n--- FAIL ---")

        print("\nShutting down...")
        proc.stdin.write(encode_message(make_request("shutdown", {}, request_id=3)))
        proc.stdin.flush()
        read_response(proc)

        proc.stdin.write(encode_message(make_notification("exit", {})))
        proc.stdin.flush()

    finally:
        proc.wait(timeout=5)
        stderr_output = proc.stderr.read().decode() if proc.stderr else ""
        if stderr_output:
            print(f"\nServer stderr:\n{stderr_output}")

    print(f"Server exited with code {proc.returncode}")


if __name__ == "__main__":
    main()
