"""Generic JSON -> dataclass config loading, so every package configures the same way.

- Keys starting with "_" are comments and are ignored.
- Missing / unknown keys fail loudly with the path of the bad section.
- Secrets never live in JSON: write "${MY_API_KEY}" and it is read from the environment.
- convert_keys() switches snake_case <-> camelCase (Python <-> the TypeScript services).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, TypeVar, get_args, get_origin, get_type_hints

T = TypeVar("T")


class ConfigError(ValueError):
    """Bad or incomplete configuration."""


# ---------------------------------------------------------------------------
# JSON -> dataclass
# ---------------------------------------------------------------------------
def strip_comments(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: strip_comments(v) for k, v in data.items() if not str(k).startswith("_")}
    if isinstance(data, list):
        return [strip_comments(v) for v in data]
    return data


def _convert(hint: Any, value: Any, where: str) -> Any:
    if is_dataclass(hint) and isinstance(value, dict):
        return build(hint, value, where)
    if get_origin(hint) is list and isinstance(value, list):
        (item_type,) = get_args(hint) or (Any,)
        if is_dataclass(item_type):
            return [build(item_type, v, f"{where}[{i}]") for i, v in enumerate(value)]
    return value


def build(cls: type[T], data: Mapping[str, Any], where: str = "config") -> T:
    """Build dataclass `cls` from a dict (recursing into nested dataclasses)."""
    data = strip_comments(dict(data))
    hints = get_type_hints(cls)
    flds = fields(cls)
    required = {f.name for f in flds if f.default is MISSING and f.default_factory is MISSING}
    missing = sorted(required - data.keys())
    unknown = sorted(data.keys() - {f.name for f in flds})
    if missing or unknown:
        raise ConfigError(
            f"Invalid config [{where}]. Missing keys: {missing}. Unknown keys: {unknown}."
        )
    return cls(**{k: _convert(hints[k], v, f"{where}.{k}") for k, v in data.items()})


def resolve_path(explicit: Optional[str | os.PathLike], env_var: str, default: Path) -> Path:
    return Path(explicit or os.environ.get(env_var) or default)


def load_json_config(
    cls: type[T],
    default_path: Path,
    env_var: str,
    path: Optional[str | os.PathLike] = None,
) -> T:
    """Load `path`, else $env_var, else `default_path`, into dataclass `cls`."""
    chosen = resolve_path(path, env_var, default_path)
    with open(chosen, encoding="utf-8") as fh:
        return build(cls, json.load(fh), chosen.name)


# ---------------------------------------------------------------------------
# Environment variables / secrets
# ---------------------------------------------------------------------------
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: Any, env: Optional[Mapping[str, str]] = None) -> Any:
    """Replace ${VAR} in strings (recursively). Raises ConfigError if VAR is not set."""
    env = os.environ if env is None else env
    if isinstance(value, str):
        def sub(m: re.Match) -> str:
            if m.group(1) not in env:
                raise ConfigError(f"Environment variable {m.group(1)} is not set")
            return env[m.group(1)]
        return _ENV_RE.sub(sub, value)
    if isinstance(value, list):
        return [expand_env(v, env) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v, env) for k, v in value.items()}
    return value


def load_dotenv_file(path: str | os.PathLike = ".env", override: bool = False) -> int:
    """Tiny .env reader (KEY=VALUE per line). Returns how many variables were set."""
    p = Path(path)
    if not p.exists():
        return 0
    count = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        if override or key not in os.environ:
            os.environ[key] = val
            count += 1
    return count


# ---------------------------------------------------------------------------
# snake_case <-> camelCase (Python <-> TypeScript)
# ---------------------------------------------------------------------------
def snake_to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


_CONVERTERS = {"camel": snake_to_camel, "snake": camel_to_snake}


def convert_keys(obj: Any, to: str) -> Any:
    """Recursively rename dict keys to 'camel' or 'snake' style (values untouched)."""
    if to not in _CONVERTERS:
        raise ConfigError(f"Unknown key style '{to}'. Use one of {sorted(_CONVERTERS)}")
    fn = _CONVERTERS[to]
    if isinstance(obj, dict):
        return {fn(k): convert_keys(v, to) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_keys(v, to) for v in obj]
    return obj
