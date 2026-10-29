from __future__ import annotations

import atexit
import select
import socket
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Sequence
from urllib.parse import quote_plus

import paramiko
import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import settings

_tunnel_lock = threading.Lock()
_tunnel: Optional["_ParamikoTunnel"] = None


class _ParamikoTunnel:
    """Local TCP forwarder over an SSH password session (Paramiko 5 compatible)."""

    def __init__(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        ssh_password: str,
        remote_host: str,
        remote_port: int,
    ):
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.local_bind_port = 0
        self._client: Optional[paramiko.SSHClient] = None
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.is_active = False

    def start(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.ssh_host,
            port=self.ssh_port,
            username=self.ssh_user,
            password=self.ssh_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30,
        )
        transport = client.get_transport()
        if transport is None:
            client.close()
            raise RuntimeError("SSH transport unavailable")
        transport.set_keepalive(30)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(32)
        server.settimeout(1.0)

        self._client = client
        self._server = server
        self.local_bind_port = server.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        self.is_active = True

    def stop(self) -> None:
        self._stop.set()
        self.is_active = False
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None

    def _accept_loop(self) -> None:
        assert self._server is not None
        assert self._client is not None
        while not self._stop.is_set():
            try:
                client_sock, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            transport = self._client.get_transport()
            if transport is None or not transport.is_active():
                client_sock.close()
                self.is_active = False
                break
            try:
                channel = transport.open_channel(
                    "direct-tcpip",
                    (self.remote_host, self.remote_port),
                    client_sock.getpeername(),
                )
            except Exception:
                client_sock.close()
                continue
            if channel is None:
                client_sock.close()
                continue
            threading.Thread(
                target=self._pipe,
                args=(client_sock, channel),
                daemon=True,
            ).start()

    @staticmethod
    def _pipe(sock: socket.socket, channel: paramiko.Channel) -> None:
        try:
            while True:
                r, _, _ = select.select([sock, channel], [], [], 1.0)
                if sock in r:
                    data = sock.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in r:
                    data = channel.recv(65536)
                    if not data:
                        break
                    sock.sendall(data)
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
            try:
                channel.close()
            except Exception:
                pass


def _start_ssh_tunnel() -> _ParamikoTunnel:
    global _tunnel
    ssh_host = settings.ssh_host.strip()
    ssh_user = settings.ssh_user.strip()
    ssh_password = settings.ssh_password or ""
    if not ssh_host:
        raise RuntimeError(
            "SSH_HOST must be set when SSH_TUNNEL_ENABLED=true. "
            "Set SSH_TUNNEL_ENABLED=false for local development."
        )
    if not ssh_user:
        raise RuntimeError(
            "SSH_USER must be set when SSH_TUNNEL_ENABLED=true"
        )
    if not ssh_password:
        raise RuntimeError(
            "SSH_PASSWORD must be set when SSH_TUNNEL_ENABLED=true"
        )
    remote_host = (settings.postgres_remote_host or settings.postgres_host).strip()
    if not remote_host:
        raise RuntimeError(
            "POSTGRES_REMOTE_HOST (or POSTGRES_HOST) must be set when SSH_TUNNEL_ENABLED=true"
        )
    tunnel = _ParamikoTunnel(
        ssh_host=ssh_host,
        ssh_port=settings.ssh_port,
        ssh_user=ssh_user,
        ssh_password=ssh_password,
        remote_host=remote_host,
        remote_port=settings.postgres_port,
    )
    tunnel.start()
    _tunnel = tunnel
    return tunnel


def _cleanup_tunnel() -> None:
    global _tunnel
    with _tunnel_lock:
        if _tunnel is not None:
            _tunnel.stop()
            _tunnel = None


atexit.register(_cleanup_tunnel)


def postgres_connect_kwargs() -> Dict[str, Any]:
    if not settings.postgres_user or not settings.postgres_db:
        raise RuntimeError(
            "POSTGRES_USER and POSTGRES_DB must be set to connect to PostgreSQL. "
            "Set DATABASE_BACKEND=sqlite for local development."
        )
    host = settings.postgres_host or "127.0.0.1"
    port = settings.postgres_port
    if settings.ssh_tunnel_enabled:
        global _tunnel
        with _tunnel_lock:
            if _tunnel is None or not _tunnel.is_active:
                _start_ssh_tunnel()
            host = "127.0.0.1"
            port = _tunnel.local_bind_port
    return {
        "host": host,
        "port": port,
        "dbname": settings.postgres_db,
        "user": settings.postgres_user,
        "password": settings.postgres_password,
    }


def build_database_url() -> str:
    if settings.database_url:
        return settings.database_url
    user = quote_plus(settings.postgres_user)
    password = quote_plus(settings.postgres_password)
    host = settings.postgres_host
    port = settings.postgres_port
    db = settings.postgres_db
    if not user or not password or not host or not db:
        raise RuntimeError(
            "Incomplete PostgreSQL configuration (POSTGRES_USER/PASSWORD/HOST/DB). "
            "Set DATABASE_BACKEND=sqlite for local development, or fill all Postgres "
            "env vars for production."
        )
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@contextmanager
def postgres_connection() -> Iterator[Any]:
    conn = psycopg2.connect(**postgres_connect_kwargs())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class PostgresCursor:
    """Thin wrapper so store code can use sqlite-style `?` placeholders."""

    def __init__(self, cursor):
        self._cursor = cursor

    @staticmethod
    def _adapt_sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> "PostgresCursor":
        self._cursor.execute(self._adapt_sql(sql), params)
        return self

    def fetchone(self) -> Optional[Any]:
        return self._cursor.fetchone()

    def fetchall(self) -> list:
        return self._cursor.fetchall()


@contextmanager
def postgres_session() -> Iterator[PostgresCursor]:
    with postgres_connection() as conn:
        cursor = PostgresCursor(conn.cursor(cursor_factory=RealDictCursor))
        try:
            yield cursor
        finally:
            cursor._cursor.close()
