import socket
import subprocess
import sys
import time
from pathlib import Path


class MCPDeployment:
    """Launch and supervise a generated MCP server (HTTP transport)."""

    def __init__(self, host: str = "127.0.0.1", port: int | None = None):
        self.process = None
        self.host = host
        self.port = port

    @property
    def url(self) -> str | None:
        """MCP endpoint a client connects to, e.g. http://127.0.0.1:8100/mcp."""
        if self.port is None:
            return None
        return f"http://{self.host}:{self.port}/mcp"

    def deploy(self, server_path: Path):
        """Start the generated MCP server as a child process."""

        self.process = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        return self.process

    def wait_until_ready(self, timeout: float = 12.0) -> bool:
        """Block until the server accepts TCP connections on its port.

        Returns True once the port is open, or False if it never came up within
        `timeout` (or the process died during startup).
        """
        if self.port is None:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            # If the process already exited, it will never become ready.
            if self.process is not None and self.process.poll() is not None:
                return False
            try:
                with socket.create_connection((self.host, self.port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.25)
        return False

    def is_running(self):
        if self.process is None:
            return False
        return self.process.poll() is None

    def stop(self):
        if self.process:
            self.process.terminate()
