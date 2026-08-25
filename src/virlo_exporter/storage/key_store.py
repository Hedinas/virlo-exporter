from __future__ import annotations

import os
from contextlib import suppress

import keyring
from keyring.errors import KeyringError

SERVICE_NAME = "Virlo Exporter"
ACCOUNT_NAME = "virlo_api_key"


class ApiKeyStore:
    """Uses Windows Credential Manager via keyring; never stores a plaintext fallback."""

    def get(self) -> str | None:
        try:
            value = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
        except KeyringError:
            value = None
        return value or os.getenv("VIRLO_API_KEY")

    def set(self, value: str) -> None:
        try:
            keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, value.strip())
        except KeyringError as exc:
            raise RuntimeError("Windows Credential Manager could not save the API key.") from exc

    def delete(self) -> None:
        with suppress(KeyringError):
            keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
