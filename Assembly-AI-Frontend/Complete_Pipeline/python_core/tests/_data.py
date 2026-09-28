"""Loads pipeline_cases.json once so test modules can parametrize from it."""

import json
from pathlib import Path

DATA = json.loads(Path(__file__).with_name("pipeline_cases.json").read_text(encoding="utf-8"))
