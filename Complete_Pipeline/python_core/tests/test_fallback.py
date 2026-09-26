from dataclasses import replace

import pytest

from _data import DATA
from src.common import ConfigError
from src.validation import MeaningValidator
from src.validation.fallback import FallbackEngine, SaferRewriter, load_fallback_config


@pytest.fixture(scope="module")
def engine():
    return FallbackEngine(MeaningValidator())


@pytest.mark.parametrize("case", DATA["fallback_cases"], ids=lambda c: c["name"])
def test_hierarchy(engine, case):
    decision = engine.resolve(case["original"], case["repaired"], case["known"])
    assert decision.source == case["source"]
    assert decision.text == case["text"]


def test_bad_output_is_never_spoken(engine, data):
    """CP-10: whatever the LLM returns, the spoken text is one of the safe candidates."""
    case = data["fallback_cases"][0]
    decision = engine.resolve(case["original"], case["repaired"])
    assert case["repaired"] not in decision.text
    assert [a.level for a in decision.rejected] == ["repaired"]


@pytest.mark.parametrize("case", DATA["rewriter_cases"], ids=lambda c: c["text"])
def test_safer_rewriter(case):
    assert SaferRewriter(load_fallback_config().safer).rewrite(case["text"]) == case["expected"]


@pytest.mark.parametrize("bad", DATA["bad_fallback_configs"], ids=lambda c: c["name"])
def test_bad_hierarchy_fails_loudly(bad):
    cfg = replace(load_fallback_config(), hierarchy=bad["hierarchy"], trusted_levels=bad["trusted_levels"])
    with pytest.raises(ConfigError):
        FallbackEngine(MeaningValidator(), cfg)


def test_hierarchy_order_is_configurable(engine, data):
    case = data["fallback_cases"][2]  # bad repair; safer would normally win
    cfg = replace(load_fallback_config(), hierarchy=["repaired", "original"])
    decision = FallbackEngine(MeaningValidator(), cfg).resolve(case["original"], case["repaired"])
    assert decision.source == "original"
