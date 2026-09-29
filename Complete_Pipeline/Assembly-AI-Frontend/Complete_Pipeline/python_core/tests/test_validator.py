"""Run from the repo root:  python -m pytest tests/test_validator.py -v

All examples live in tests/validator_cases.json - add cases there, not here.
"""

import json
import re
from pathlib import Path

import pytest

from src.validation import (
    Check,
    MeaningValidator,
    Toolkit,
    ValidatorConfig,
    load_config,
    validate,
    validate_with_detail,
)
from src.validation.config import CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH

DATA = json.loads(Path(__file__).with_name("validator_cases.json").read_text(encoding="utf-8"))


def apply_changes(cfg, changes):
    for ch in changes:
        current = getattr(getattr(cfg, ch["section"]), ch["key"])
        value = list(current) + ch["value"] if ch["mode"] == "extend" else ch["value"]
        cfg = cfg.override(ch["section"], **{ch["key"]: value})
    return cfg


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", DATA["cases"], ids=[c["name"] for c in DATA["cases"]])
def test_cases(case):
    res = validate_with_detail(case["original"], case["repaired"], case["known_entities"])
    assert res["reason"] == case["expected"], (
        f"expected {case['expected']}, got {res['reason']} ({res['detail']})\n"
        f"  orig: {case['original']}\n  rep:  {case['repaired']}"
    )
    assert res["approved"] == (case["expected"] == "approved")


def test_validate_returns_contract_shape():
    first = DATA["cases"][0]
    assert set(validate(first["original"], first["repaired"]).keys()) == {"approved", "reason"}


# ---------------------------------------------------------------------------
# Config drives everything
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sc", DATA["config_scenarios"], ids=[s["name"] for s in DATA["config_scenarios"]]
)
def test_config_changes_behaviour(sc):
    base = load_config()
    assert MeaningValidator(base).validate(sc["original"], sc["repaired"])["reason"] == sc["expect_default"]
    custom = apply_changes(base, sc["changes"])
    assert MeaningValidator(custom).validate(sc["original"], sc["repaired"])["reason"] == sc["expect_custom"]


def test_check_list_is_configurable():
    sc = DATA["checks_scenario"]
    base = load_config()
    assert MeaningValidator(base).validate(sc["original"], sc["repaired"])["reason"] == sc["expect_default"]
    only = ValidatorConfig.from_dict({**json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")), "checks": sc["checks"]})
    assert MeaningValidator(only).validate(sc["original"], sc["repaired"])["reason"] == sc["expect_custom"]


def test_unknown_check_name_fails_loudly():
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["checks"] = [DATA["unknown_check_name"]]
    with pytest.raises(ValueError, match="Unknown check"):
        MeaningValidator(ValidatorConfig.from_dict(raw))


def test_config_loaded_from_env_var(tmp_path, monkeypatch):
    ov = DATA["env_override"]
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw[ov["section"]][ov["key"]] = ov["value"]
    p = tmp_path / "custom.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(p))
    assert getattr(getattr(load_config(), ov["section"]), ov["key"]) == ov["value"]


def test_bad_config_fails_loudly():
    with pytest.raises(ValueError, match="Missing keys"):
        ValidatorConfig.from_dict({"months": []})


def test_bad_section_fails_loudly():
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["dates"].pop("months")
    with pytest.raises(ValueError, match=r"\[dates\]"):
        ValidatorConfig.from_dict(raw)


# ---------------------------------------------------------------------------
# Extensible: teammates can plug in their own check
# ---------------------------------------------------------------------------
def test_custom_check_can_be_plugged_in():
    case = DATA["custom_check_case"]

    class ShoutingCheck(Check):
        name = "shouting"
        reason = case["expected"]

        def run(self, ctx):
            return "shouting" if ctx.repaired.text.isupper() else None

    validator = MeaningValidator(checks=[ShoutingCheck(None, None)])
    assert validator.validate(case["original"], case["repaired"])["reason"] == case["expected"]


# ---------------------------------------------------------------------------
# Reusable: extractors work on their own (e.g. for Person 2)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def tools():
    return Toolkit.from_config(load_config())


@pytest.mark.parametrize("c", DATA["extractor_cases"]["numbers"])
def test_number_extractor(tools, c):
    assert tools.numbers.extract(c["text"]) == c["expected"]


@pytest.mark.parametrize("c", DATA["extractor_cases"]["dates"])
def test_date_extractor(tools, c):
    match = tools.dates.extract(c["text"])
    assert match.tokens == c["tokens"]
    if c["rest_has_no_digits"]:
        assert not re.search(r"\d", match.rest)


@pytest.mark.parametrize("c", DATA["extractor_cases"]["entities"])
def test_entity_extractor(tools, c):
    assert tools.entities.extract(c["text"], c["known"]) == c["expected"]
