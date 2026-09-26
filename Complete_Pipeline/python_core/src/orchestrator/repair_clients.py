"""How the orchestrator talks to Person 2's repair step.

Any object with  repair(event: TranscriptEvent) -> RepairResult  works
(RepairProvider). Two are included, chosen in repair_config.json:
  - MockRepairClient : offline stand-in so Person 3 never waits for Person 2
  - HttpRepairClient : calls Person 2's TypeScript service over HTTP (JSON)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol
from urllib import error, request

from src.common import ConfigError, build, convert_keys, expand_env, load_json_config
from src.validation.fallback import SaferRewriter

try:
    from src.contracts import RepairResult, TranscriptEvent
except ImportError:  # pragma: no cover
    from contracts import RepairResult, TranscriptEvent

DEFAULT_REPAIR_CONFIG_PATH = Path(__file__).with_name("repair_config.json")
REPAIR_CONFIG_ENV_VAR = "CLEARVOICE_REPAIR_CONFIG"


class RepairError(Exception):
    """Person 2's step failed or returned something unusable."""


class RepairProvider(Protocol):
    def repair(self, event: TranscriptEvent) -> RepairResult: ...


@dataclass(frozen=True)
class RepairConfig:
    provider: str
    providers: dict


def load_repair_config(path=None) -> RepairConfig:
    return load_json_config(RepairConfig, DEFAULT_REPAIR_CONFIG_PATH, REPAIR_CONFIG_ENV_VAR, path)


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MockRepairConfig:
    result_type: str
    version: int
    confidence: float


class MockRepairClient:
    """Pretends to be the LLM. `overrides` maps an original text to the (possibly BAD)
    output you want the 'LLM' to return - handy for testing the validator + fallback."""

    def __init__(self, cfg: MockRepairConfig, rewriter: SaferRewriter, overrides: Optional[dict] = None):
        self.cfg = cfg
        self._rewriter = rewriter
        self._overrides = overrides or {}

    def repair(self, event: TranscriptEvent) -> RepairResult:
        text = event["text"]
        return {
            "type": self.cfg.result_type,
            "version": self.cfg.version,
            "session_id": event["session_id"],
            "utterance_id": event["utterance_id"],
            "original_text": text,
            "repaired_text": self._overrides.get(text, self._rewriter.rewrite(text)),
            "confidence": self.cfg.confidence,
            "changes": [],
        }


# ---------------------------------------------------------------------------
# HTTP (Person 2's TypeScript service)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HttpRepairConfig:
    url: str
    method: str
    headers: dict
    wire_case: str  # key style the TypeScript side uses: "camel" or "snake"
    timeout_s: float
    required_fields: list  # snake_case names that must be in the response


class HttpRepairClient:
    def __init__(self, cfg: HttpRepairConfig):
        self.cfg = cfg
        self._headers = expand_env(cfg.headers)

    def repair(self, event: TranscriptEvent) -> RepairResult:
        cfg = self.cfg
        payload = json.dumps(convert_keys(dict(event), cfg.wire_case)).encode("utf-8")
        req = request.Request(cfg.url, data=payload, headers=self._headers, method=cfg.method)
        try:
            with request.urlopen(req, timeout=cfg.timeout_s) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RepairError(f"repair service HTTP {exc.code}: {exc.reason}") from exc
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RepairError(f"repair service call failed: {exc}") from exc

        result = convert_keys(raw, "snake")
        missing = [f for f in cfg.required_fields if f not in result]
        if missing:
            raise RepairError(f"repair service response is missing {missing}")
        return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_repair_client(
    config: Optional[RepairConfig] = None,
    rewriter: Optional[SaferRewriter] = None,
    mock_overrides: Optional[dict] = None,
) -> RepairProvider:
    config = config or load_repair_config()
    settings = config.providers.get(config.provider)
    if settings is None:
        raise ConfigError(f"repair provider '{config.provider}' is not defined in repair_config.json")
    if config.provider == "http":
        return HttpRepairClient(build(HttpRepairConfig, settings, "repair.providers.http"))
    if config.provider == "mock":
        if rewriter is None:
            raise ConfigError("the mock repair provider needs a SaferRewriter")
        return MockRepairClient(build(MockRepairConfig, settings, "repair.providers.mock"), rewriter, mock_overrides)
    raise ConfigError(f"Unknown repair provider '{config.provider}'")
