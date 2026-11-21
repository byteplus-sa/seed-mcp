"""Synthetic-only private chart and real proxy acceptance, with no providers."""

import hashlib
import http.client
import json
import os
import socket
import ssl
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from tests.unit.test_vke_chart import CHART, documents, executable, render

CADDYFILE = CHART / "files/Caddyfile.apig-staging"
BACKEND = "backend.example.invalid"
PUBLIC = "mcp.example.invalid"


def staging(**overrides: Any) -> dict[str, Any]:
    return {
        "backendHost": BACKEND,
        "service": {"mode": "apig-staging", "subnetId": "", "sourceRanges": ["10.80.48.0/20"]},
        **overrides,
    }


def test_private_render_has_no_public_clb_and_correct_config(tmp_path: Path) -> None:
    items = documents(render(tmp_path, staging()))
    service = next(item for item in items if item["kind"] == "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"] == [
        {"name": "https", "port": 8443, "targetPort": "https", "protocol": "TCP"}
    ]
    assert "annotations" not in service["metadata"]
    assert "loadBalancerSourceRanges" not in service["spec"]
    policy = next(item for item in items if item["kind"] == "NetworkPolicy")["spec"]
    assert policy["policyTypes"] == ["Ingress"]
    assert policy["podSelector"]["matchLabels"] == service["spec"]["selector"]
    assert policy["ingress"] == [
        {
            "from": [{"ipBlock": {"cidr": "10.80.48.0/20"}}],
            "ports": [{"protocol": "TCP", "port": 8443}],
        }
    ]
    config = next(item for item in items if item["kind"] == "ConfigMap")
    assert config["data"]["Caddyfile"] == CADDYFILE.read_text()
    deployment = next(item for item in items if item["kind"] == "Deployment")
    checksum = deployment["spec"]["template"]["metadata"]["annotations"]["checksum/proxy"]
    assert checksum == hashlib.sha256(CADDYFILE.read_bytes()).hexdigest()
    normal = next(item for item in documents(render(tmp_path)) if item["kind"] == "Deployment")
    assert checksum != normal["spec"]["template"]["metadata"]["annotations"]["checksum/proxy"]


@pytest.mark.parametrize(
    "override",
    [
        {"backendHost": ""},
        {"backendHost": PUBLIC},
        {"backendHost": "bad..example.invalid"},
        {
            "temporaryUpload": {
                "enabled": True,
                "existingSecret": "synthetic-uploads",  # pragma: allowlist secret
            }
        },
        {"service": {"mode": "unknown"}},
        {"service": {"subnetId": "subnet-unwanted"}},
        *[
            {"service": {"mode": "apig-staging", "subnetId": "", "sourceRanges": [cidr]}}
            for cidr in (
                "0.0.0.0/0",
                "10.0.0.0/7",
                "172.16.0.0/11",
                "192.168.0.0/15",
                "172.32.0.0/16",
                "192.0.2.0/24",
                "169.254.0.0/16",
            )
        ],
    ],
)
def test_unsafe_staging_inputs_fail(tmp_path: Path, override: dict[str, Any]) -> None:
    values = staging()
    for name, value in override.items():
        if name == "service":
            values[name] |= value
        else:
            values[name] = value
    assert render(tmp_path, values).returncode != 0


@pytest.mark.parametrize("cidr", ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])
def test_private_ranges_render(tmp_path: Path, cidr: str) -> None:
    values = staging()
    values["service"]["sourceRanges"] = [cidr]
    documents(render(tmp_path, values))


def test_real_staging_proxy_refuses_credentials_and_canonicalizes_headers(
    tmp_path: Path,
    socket_enabled: None,
) -> None:
    binary = executable("CADDY_BIN", "caddy")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, BACKEND)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=5))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(BACKEND)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "tls.crt", tmp_path / "tls.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    seen: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(dict(self.headers))
            body = b"synthetic-backend"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET

        def log_message(self, *_args: object) -> None:
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "MCP_PUBLIC_HOST": PUBLIC,
        "MCP_BACKEND_HOST": BACKEND,
        "MCP_PROXY_PORT": str(port),
        "MCP_PORT": str(backend.server_port),
        "MCP_TLS_CERT_FILE": str(cert_path),
        "MCP_TLS_KEY_FILE": str(key_path),
    }
    adapted = subprocess.run(
        [binary, "adapt", "--config", str(CADDYFILE)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert adapted.returncode == 0, adapted.stderr
    config = json.loads(adapted.stdout)
    assert config["admin"]["disabled"]
    assert config["logging"]["logs"]["default"]["writer"]["output"] == "discard"
    process = subprocess.Popen(
        [binary, "run", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    context = ssl.create_default_context(cafile=str(cert_path))

    def request(path: str, headers: dict[str, str] | None = None) -> int:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.sock = context.wrap_socket(
            socket.create_connection(("127.0.0.1", port), timeout=3), server_hostname=BACKEND
        )
        try:
            connection.request(
                "POST" if path == "/mcp" else "GET",
                path,
                headers={"Host": PUBLIC, **(headers or {})},
            )
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    try:
        deadline = time.monotonic() + 10
        while True:
            assert process.poll() is None, "Staging Caddy exited before acceptance"
            try:
                assert request("/health") == 200
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        seen.clear()
        for path in ("/health", "/mcp", "/ready"):
            for header in (
                "x-modelark-api-key",
                "X-Seed-Speech-Api-Key",
                "x-mcp-client-secret",
                "Authorization",
            ):
                for value in ("synthetic-only", ""):
                    assert request(path, {header: value}) == 403
        assert seen == []
        assert request("/ready") == 404
        assert request("/metrics") == 404
        assert (
            request(
                "/mcp",
                {
                    "Forwarded": "for=203.0.113.1",
                    "X-Forwarded-For": "203.0.113.1",
                    "X-Forwarded-Host": "wrong.invalid",
                    "X-Forwarded-Proto": "http",
                    "X-Seed-Staging-Probe": "synthetic-only",
                },
            )
            == 200
        )
        assert seen[-1]["Host"] == PUBLIC
        assert seen[-1]["X-Forwarded-Host"] == PUBLIC
        assert seen[-1]["X-Forwarded-Proto"] == "https"
        assert seen[-1]["X-Forwarded-For"] == "127.0.0.1"
        assert "Forwarded" not in seen[-1]
        assert "X-Seed-Staging-Probe" not in seen[-1]
        assert request("/health", {"Host": "wrong.invalid"}) == 404
    finally:
        process.terminate()
        process.wait(timeout=10)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
