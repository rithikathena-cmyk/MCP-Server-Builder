import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from backend.config import settings


class MCPDeployment:
    """Launch and supervise a generated MCP server (HTTP transport)."""

    def __init__(self, host: str = "127.0.0.1", port: Optional[int] = None):
        self.process = None
        self.host = host
        self.port = port

    @property
    def url(self) -> Optional[str]:
        """MCP endpoint a client connects to, e.g. http://127.0.0.1:8100/mcp."""
        if self.port is None:
            return None
        return f"http://{self.host}:{self.port}/mcp"

    def deploy(self, server_path: Path, db_url: str):
        """Start the generated MCP server as a child process.

        The database connection string is passed via the MCP_DB_URL environment
        variable rather than baked into the file, so credentials never touch disk.
        The server's audit log path is passed the same way (MCP_AUDIT_LOG), one
        file per deployment, so every query attempt is recorded regardless of
        whether it arrives via this API or a host application connecting to the
        generated server directly.
        """
        settings.audit_log_dir.mkdir(parents=True, exist_ok=True)
        audit_log_path = settings.audit_log_dir / f"{server_path.stem}.jsonl"
        env = {**os.environ, "MCP_DB_URL": db_url, "MCP_AUDIT_LOG": str(audit_log_path)}

        self.process = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(Path(__file__).parent.parent),  # project root
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
            if self.process is not None and self.process.poll() is not None:
                return False
            try:
                with socket.create_connection((self.host, self.port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.25)
        return False

    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
