import os

import pytest

from src.common import ConfigError, build, convert_keys, expand_env, load_dotenv_file


def test_convert_keys_both_ways(data):
    c = data["common"]
    assert convert_keys(c["snake"], "camel") == c["camel"]
    assert convert_keys(c["camel"], "snake") == c["snake"]


def test_convert_keys_unknown_style(data):
    with pytest.raises(ConfigError):
        convert_keys(data["common"]["snake"], "kebab")


def test_expand_env_missing_variable_fails(data):
    with pytest.raises(ConfigError, match="not set"):
        expand_env(data["common"]["env_missing"], env={})


def test_expand_env_replaces_nested_values():
    assert expand_env({"a": ["x-${K}"]}, env={"K": "1"}) == {"a": ["x-1"]}


def test_build_reports_missing_and_unknown_keys():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Sample:
        a: int
        b: str

    with pytest.raises(ConfigError, match=r"Missing keys: \['b'\]. Unknown keys: \['zzz'\]"):
        build(Sample, {"a": 1, "zzz": 2}, "sample")
    assert build(Sample, {"a": 1, "b": "x", "_comment": "ignored"}) == Sample(1, "x")


def test_load_dotenv_file(tmp_path, monkeypatch, data):
    c = data["common"]
    f = tmp_path / ".env"
    f.write_text(c["dotenv_text"], encoding="utf-8")
    for k in c["dotenv_expected"]:
        monkeypatch.delenv(k, raising=False)
    assert load_dotenv_file(f) == len(c["dotenv_expected"])
    for k, v in c["dotenv_expected"].items():
        assert os.environ[k] == v
        monkeypatch.delenv(k)
