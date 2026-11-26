"""Private-runner Helm delivery; see specs/SPEC_VKE_DEPLOYMENT.md.

No IAM federation, infrastructure provisioning, provider calls or secret sync.
Operator-owned kubeconfig/values stay outside the checkout and command output
is captured, never relayed to public Actions logs.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CHART = Path(__file__).resolve().parents[1] / "deploy" / "helm" / "seed-mcp"
IMAGE = re.compile(r"ghcr\.io/byteplus-sa/seed-mcp@sha256:[0-9a-f]{64}")
NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def private_file(path: Path) -> Path:
    """Require an explicit owner-only file outside the source checkout."""
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("Use absolute operator paths without symlinks.")
    if path.is_relative_to(CHART.parents[2]):
        raise ValueError("Operator files must be outside the checkout.")
    parent, metadata = path.parent.lstat(), path.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.getuid()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError("Operator files require same-owner 0700 parents and 0600 regular files.")
    return path


def private_server(server: str) -> None:
    """Reject public API access, loopback, proxy URLs and insecure origins."""
    parsed = urlsplit(server)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443, 6443)
    ):
        raise ValueError("Select the exact private HTTPS Kubernetes API origin.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not any(ipaddress.ip_address(row[4][0]) in network for network in PRIVATE_NETWORKS)
        for row in addresses
    ):
        raise ValueError("Kubernetes API must resolve only to RFC1918 private addresses.")


class Delivery:
    """Execute one explicitly targeted invocation with isolated tool configuration."""

    def __init__(self, args: argparse.Namespace, scratch: Path) -> None:
        self.args = args
        self.scratch = scratch
        self.tools: dict[str, str] = {}
        for name in ("kubectl", "helm", "openssl"):
            executable = shutil.which(name)
            if executable is None:
                raise ValueError(
                    "Install reviewed kubectl, Helm and OpenSSL on the private runner."
                )
            self.tools[name] = str(Path(executable).resolve())
        self.env = {"PATH": os.defpath, "HOME": str(scratch), "LANG": "C"}
        for name in ("CACHE", "CONFIG", "DATA"):
            location = scratch / name.lower()
            location.mkdir(mode=0o700)
            self.env[f"HELM_{name}_HOME"] = str(location)
        plugins = scratch / "plugins"
        plugins.mkdir(mode=0o700)
        self.env["HELM_PLUGINS"] = str(plugins)

    def run(self, tool: str, *arguments: str, timeout: int = 60) -> str:
        result = subprocess.run(
            [self.tools[tool], *arguments],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        return result.stdout

    def kube(self, *arguments: str) -> str:
        return self.run(
            "kubectl",
            "--kubeconfig",
            str(self.args.kubeconfig),
            "--context",
            self.args.context,
            "--request-timeout=45s",
            *arguments,
        )

    def document(self, *arguments: str) -> dict[str, Any]:
        result = json.loads(self.kube(*arguments))
        if not isinstance(result, dict):
            raise ValueError("Invalid Kubernetes metadata response.")
        return result

    def helm_arguments(self) -> list[str]:
        return [
            "--kubeconfig",
            str(self.args.kubeconfig),
            "--kube-context",
            self.args.context,
            "--namespace",
            self.args.namespace,
            "--values",
            str(self.args.values),
            "--set-string",
            f"image={self.args.image}",
            "--set-string",
            f"publicHost={self.args.public_host}",
            "--set-string",
            f"service.mode={self.args.service_mode}",
            "--set",
            f"service.productionConfirmed={str(self.args.production_approved).lower()}",
            "--set-string",
            f"backendHost={self.args.backend_host}",
            "--set-string",
            f"identitySecret.name={self.args.identity_secret}",
            "--set-string",
            "identitySecret.hmacKey=MCP_IDENTITY_HMAC_KEY",
            "--set-string",
            "identitySecret.versionKey=MCP_IDENTITY_KEY_VERSION",
            "--set-string",
            f"tlsSecretName={self.args.tls_secret}",
        ]

    def preflight(self) -> None:
        config = self.document("config", "view", "--minify", "--output=json")
        clusters, users = config.get("clusters", []), config.get("users", [])
        if len(clusters) != 1 or len(users) != 1:
            raise ValueError("Select one explicit Kubernetes context and identity.")
        cluster, user = clusters[0]["cluster"], users[0]["user"]
        if (
            cluster.get("server") != self.args.api_server
            or cluster.get("insecure-skip-tls-verify")
            or cluster.get("proxy-url")
            or not (
                cluster.get("certificate-authority") or cluster.get("certificate-authority-data")
            )
            or any(name in user for name in ("exec", "auth-provider", "username", "password"))
        ):
            raise ValueError(
                "Kubeconfig must match the verified API, CA and explicit token/certificate."
            )
        private_server(self.args.api_server)
        version = self.document("version", "--output=json")
        minor = int(str(version["serverVersion"]["minor"]).rstrip("+"))
        client_minor = int(str(version["clientVersion"]["minor"]).rstrip("+"))
        if version["serverVersion"]["major"] != "1" or minor < 30 or abs(client_minor - minor) > 1:
            raise ValueError("Use Kubernetes >=1.30 and a compatible reviewed kubectl.")
        self.document("get", "namespace", self.args.namespace, "--output=json")
        nodes = self.document("get", "nodes", "--output=json").get("items", [])
        ready = [
            node
            for node in nodes
            if not node.get("spec", {}).get("unschedulable")
            and not any(
                taint.get("effect") in ("NoSchedule", "NoExecute")
                for taint in node.get("spec", {}).get("taints", [])
            )
            and any(
                row.get("type") == "Ready" and row.get("status") == "True"
                for row in node.get("status", {}).get("conditions", [])
            )
        ]
        if len(ready) < 2:
            raise ValueError(
                "Two Ready schedulable nodes are required; verify additional headroom."
            )
        if (
            len(self.document("get", "--raw=/apis/metrics.k8s.io/v1beta1/nodes").get("items", []))
            < 2
        ):
            raise ValueError("The HPA metrics API must report at least two nodes.")
        identity = self.secret(self.args.identity_secret)
        key = base64.b64decode(identity["MCP_IDENTITY_HMAC_KEY"], validate=True).decode("ascii")
        key_version = base64.b64decode(identity["MCP_IDENTITY_KEY_VERSION"], validate=True).decode(
            "ascii"
        )
        if not re.fullmatch(r"[0-9a-f]{64}", key) or not re.fullmatch(r"[1-9][0-9]*", key_version):
            raise ValueError("The existing identity Secret must contain a valid HMAC and version.")
        tls = self.secret(self.args.tls_secret, expected_type="kubernetes.io/tls")
        certificate, private_key = self.scratch / "tls.crt", self.scratch / "tls.key"
        for field, path in (("tls.crt", certificate), ("tls.key", private_key)):
            with path.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(base64.b64decode(tls[field], validate=True))
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_cert_chain(certificate, private_key)
        tls_host = (
            self.args.backend_host
            if self.args.service_mode in ("apig-staging", "apig-production")
            else self.args.public_host
        )
        hostname_check = self.run(
            "openssl",
            "x509",
            "-in",
            str(certificate),
            "-checkhost",
            tls_host,
            "-noout",
        )
        if f"Hostname {tls_host} does match certificate" not in hostname_check.splitlines():
            raise ValueError("The existing TLS certificate must match the selected TLS hostname.")
        self.run("openssl", "x509", "-in", str(certificate), "-checkend", "86400", "-noout")
        self.run("helm", "lint", str(CHART), "--strict", *self.helm_arguments())

    def secret(self, name: str, *, expected_type: str | None = None) -> dict[str, str]:
        result = self.document(
            "get", "secret", name, "--namespace", self.args.namespace, "--output=json"
        )
        if expected_type is not None and result.get("type") != expected_type:
            raise ValueError("The existing TLS Secret must have type kubernetes.io/tls.")
        data = result.get("data")
        if not isinstance(data, dict):
            raise ValueError("Existing identity/TLS Secret data is missing.")
        return data

    def deploy(self) -> None:
        # One Helm dispatch only. Do not automatically roll back or retry partial outcomes.
        self.run(
            "helm",
            "upgrade",
            "--install",
            self.args.release,
            str(CHART),
            "--wait",
            "--timeout=15m",
            "--history-max=5",
            *self.helm_arguments(),
            timeout=960,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "deploy"))
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--values", type=Path, required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--api-server", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--release", default="seed-mcp")
    parser.add_argument("--image", required=True)
    parser.add_argument("--public-host", required=True)
    parser.add_argument(
        "--service-mode", choices=("public-clb", "apig-staging", "apig-production"), required=True
    )
    parser.add_argument("--backend-host", default="")
    parser.add_argument(
        "--production-approved",
        action="store_true",
        help="Acknowledge the documented backend trust decision and remaining production gates; not a TLS test or waiver by itself.",
    )
    parser.add_argument("--identity-secret", required=True)
    parser.add_argument("--tls-secret", required=True)
    parser.add_argument("--prerequisites-confirmed", action="store_true")
    args = parser.parse_args(argv)
    dispatched = False
    try:
        if not args.prerequisites_confirmed:
            raise ValueError(
                "Confirm operator-owned CCM, capacity, source restrictions and addons first."
            )
        if not IMAGE.fullmatch(args.image):
            raise ValueError("Select a sha256-pinned image from the Seed MCP GHCR repository.")
        if not args.context or any(ord(char) < 33 for char in args.context):
            raise ValueError("Supply an explicit reviewed Kubernetes context.")
        if len(args.public_host) > 253 or not HOST.fullmatch(args.public_host):
            raise ValueError("Supply the reviewed public DNS hostname.")
        if args.production_approved != (args.service_mode == "apig-production"):
            raise ValueError("Production mode requires its separate approval acknowledgement.")
        if args.service_mode in ("apig-staging", "apig-production"):
            if (
                len(args.backend_host) > 253
                or not HOST.fullmatch(args.backend_host)
                or args.backend_host == args.public_host
            ):
                raise ValueError("APIG requires a distinct reviewed private TLS hostname.")
        elif args.backend_host:
            raise ValueError("backend-host is accepted only for APIG modes.")
        for value in (args.namespace, args.release, args.identity_secret, args.tls_secret):
            if not NAME.fullmatch(value):
                raise ValueError("Use explicit DNS-label namespace, release and Secret names.")
        if args.namespace in ("default", "kube-system", "kube-public", "kube-node-lease"):
            raise ValueError(
                "Use a dedicated application namespace, not a default/system namespace."
            )
        if args.identity_secret == args.tls_secret:
            raise ValueError("Identity and TLS must use distinct existing Secrets.")
        args.kubeconfig, args.values = private_file(args.kubeconfig), private_file(args.values)
        with tempfile.TemporaryDirectory(prefix="seed-vke-delivery-") as temporary:
            delivery = Delivery(args, Path(temporary))
            delivery.preflight()
            print(
                "Private cluster and chart preflight passed; live acceptance remains separate.",
                flush=True,
            )
            if args.operation == "deploy":
                dispatched = True
                delivery.deploy()
                print(
                    "Helm delivery completed. Live routing and scaling acceptance remain separate."
                )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        message = (
            "Helm delivery failed or timed out; inspect the release before retrying. Outcome may be partial."
            if dispatched
            else "VKE preflight failed; inspect protected configuration and operator prerequisites. No Helm dispatch."
        )
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
