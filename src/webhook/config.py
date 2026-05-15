"""Application configuration via environment variables.

All settings use the WEBHOOK_ prefix.
Validated at process startup — fail fast before accepting any traffic.
"""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from webhook.domain.types import LabelMap


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEBHOOK_",
        extra="ignore",  # tolerate extra env vars from K8s injections
        frozen=True,
    )

    # TLS — paths to files baked into the Docker image by cert-gen stage
    tls_cert_path: Path = Path("/app/certs/tls.crt")
    tls_key_path: Path = Path("/app/certs/tls.key")

    # Server
    port: Annotated[int, Field(ge=1024, le=65535)] = 8443
    workers: Annotated[int, Field(ge=1, le=32)] = 4

    # Observability
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_sample_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0
    slow_request_threshold_ms: Annotated[int, Field(gt=0)] = 500

    # Label injection — JSON-encoded dict from env var
    # Example: WEBHOOK_CUSTOM_LABELS='{"team":"platform","env":"prod"}'
    custom_labels: LabelMap = Field(default_factory=dict)

    @field_validator("tls_cert_path", "tls_key_path", mode="after")
    @classmethod
    def must_exist(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"TLS file not found: {v}")
        return v

    @field_validator("custom_labels", mode="before")
    @classmethod
    def parse_labels_json(cls, v: object) -> object:
        """Accept custom_labels as a JSON string from env var or a dict."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError as exc:
                raise ValueError(f"WEBHOOK_CUSTOM_LABELS must be valid JSON: {exc}") from exc
        return v


_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the singleton AppConfig instance.

    TLS path validation is skipped in test environments by setting
    WEBHOOK_TLS_CERT_PATH and WEBHOOK_TLS_KEY_PATH to existing test fixtures.
    """
    global _config
    if _config is None:
        _config = AppConfig()
    return _config
