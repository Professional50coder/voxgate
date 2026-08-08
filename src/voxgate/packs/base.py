from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from pydantic import BaseModel
from voxgate.ml.scorecard import Scorecard

class CheckResult(BaseModel):
    check_name: str
    status: str            # "clear" | "review" | "hit"
    score: float
    details: dict

@dataclass
class Pack:
    pack_id: str
    display_name: str
    gate_role: str
    low_threshold: float
    high_threshold: float
    schema_model: type[BaseModel]
    reask_hints: dict[str, str]
    prompt: str
    checks: list[Callable[[dict], CheckResult]]
    scorecard: Scorecard
    feature_field_hints: dict[str, str]
    path: Path
