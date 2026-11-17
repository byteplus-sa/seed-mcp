"""Loopback-only operations listener from specs/SPEC_VKE_DEPLOYMENT.md.

Public HTTP remains unchanged under specs/SPEC_HOSTED_BYOK.md.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import TCPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ark_mcp.observability.logger import warning as log_warning
from ark_mcp.sqlite_io import drain_task


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/metrics":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = generate_latest()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE_LATEST)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class _MetricsServer(HTTPServer):
    def __init__(self, port: int) -> None:
        self._request_lock = threading.Lock()
        self._active_request: socket.socket | None = None
        self._closing = False
        super().__init__(("127.0.0.1", port), _MetricsHandler)

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = int(self.server_address[1])

    def process_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        if not isinstance(request, socket.socket):
            raise TypeError("Private metrics requires a TCP connection.")
        with self._request_lock:
            if self._closing:
                self.close_request(request)
                return
            self._active_request = request
        try:
            request.settimeout(2.0)
            super().process_request(request, client_address)
        finally:
            with self._request_lock:
                self._active_request = None

    def interrupt_request(self) -> None:
        with self._request_lock:
            self._closing = True
            if self._active_request is not None:
                with suppress(OSError):
                    self._active_request.shutdown(socket.SHUT_RDWR)

    def handle_error(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        log_warning("private_metrics_request_failed")


class MetricsListener:
    """Own one private HTTP server and drain its thread before closing the socket."""

    def __init__(self, port: int) -> None:
        self._close_task: asyncio.Task[None] | None = None
        try:
            self._server = _MetricsServer(port)
        except OSError:
            raise RuntimeError(
                "Private metrics listener could not bind its loopback port."
            ) from None
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="seed-mcp-metrics",
            daemon=False,
        )
        try:
            self._thread.start()
        except BaseException:
            self._server.server_close()
            raise

    @property
    def port(self) -> int:
        return self._server.server_port

    def _close(self) -> None:
        try:
            self._server.interrupt_request()
            self._server.shutdown()
            self._thread.join()
        finally:
            self._server.server_close()

    async def close(self) -> None:
        """Interrupt an incomplete scrape, join the worker, and release the listening socket."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(asyncio.to_thread(self._close))
        await drain_task(self._close_task)
