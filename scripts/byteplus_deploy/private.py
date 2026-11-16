"""Allowlisted operator settings and host-bound encrypted transfer."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import secrets
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .workspace import ROOT

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def validator() -> ModuleType:
    """Load the existing pure host validator without importing the MCP server."""
    path = ROOT / "deploy/terraform/byteplus/scripts/check_env.py"
    spec = importlib.util.spec_from_file_location("deployment_env_validator", path)
    if spec is None or spec.loader is None:
        raise ValueError("Host validator is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IDENTITY_SETTINGS = frozenset(validator().IDENTITY_SETTINGS)


def configuration_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def make_configuration(operator_file: Path, hostname: str) -> bytes:
    """Load operator-only inputs; never generate a client credential."""
    import os

    checker = validator()
    original = checker.load_environment(operator_file, expected_uid=os.getuid())
    return make_configuration_values(original, hostname)


def make_configuration_values(original: dict[str, str], hostname: str) -> bytes:
    """Build operator configuration per specs/SPEC_HOSTED_BYOK.md."""
    checker = validator()
    if set(original) - checker.HOSTED_SETTINGS:
        raise ValueError(
            "Hosted inputs must contain only operator settings, never customer keys or job settings."
        )
    template = ROOT / "deploy/compose/.env.example"
    values = checker.parse_environment(template.read_text())
    values.update(original)
    values["MCP_PUBLIC_HOST"] = hostname
    for value in values.values():
        if not isinstance(value, str) or any(
            ord(character) < 32 or ord(character) > 126 or character in "$`#\"'\\"
            for character in value
        ):
            raise ValueError("Operator settings must be plain literal ASCII values.")
    checker.validate_environment(values)
    return "".join(f"{key}={value}\n" for key, value in values.items()).encode()


def replace_operator_identity(payload: bytes, identity: dict[str, str]) -> bytes:
    """Replace only operator identity; changes reset scopes without a recovery bridge."""
    checker = validator()
    checker.validate_environment(checker.parse_environment(payload.decode()))
    if set(identity) != IDENTITY_SETTINGS:
        raise ValueError("Only the complete operator HMAC identity may be synced.")
    checker.validate_identity(identity)
    lines = payload.decode().splitlines(keepends=True)
    result = []
    for line in lines:
        key = line.partition("=")[0]
        if key not in IDENTITY_SETTINGS:
            result.append(line)
    if result and not result[-1].endswith("\n"):
        result[-1] += "\n"
    result.extend(f"{key}={identity[key]}\n" for key in sorted(IDENTITY_SETTINGS))
    return "".join(result).encode()


def encrypt_payload(payload: bytes, public_pem: bytes, instance_id: str) -> dict[str, str]:
    """Encrypt to the verified guest public key and bind ciphertext to its ID."""
    public_key = serialization.load_pem_public_key(public_pem)
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 3072:
        raise ValueError("Guest transfer key must be RSA with at least 3072 bits.")
    symmetric_key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(symmetric_key).encrypt(nonce, payload, instance_id.encode())
    wrapped = public_key.encrypt(
        symmetric_key,
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    return {
        "wrapped_key": base64.b64encode(wrapped).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
