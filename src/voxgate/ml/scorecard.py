import math
from typing import Callable
from pydantic import BaseModel

class FeatureContribution(BaseModel):
    feature: str
    value: float
    weight: float
    contribution: float

class ScoreResult(BaseModel):
    probability: float
    band: str
    contributions: list[FeatureContribution]
    bias: float

class Feature:
    def __init__(self, name: str, weight: float, extractor: Callable[[dict], float]):
        self.name, self.weight, self.extractor = name, weight, extractor

class Scorecard:
    def __init__(self, features: list[Feature], bias: float,
                 low_threshold: float, high_threshold: float):
        self.features, self.bias = features, bias
        self.low_threshold, self.high_threshold = low_threshold, high_threshold

    def score(self, data: dict) -> ScoreResult:
        contribs = []
        total = self.bias
        for f in self.features:
            x = float(f.extractor(data))
            c = x * f.weight
            total += c
            contribs.append(FeatureContribution(
                feature=f.name, value=round(x, 4),
                weight=f.weight, contribution=round(c, 4)))
        p = 1.0 / (1.0 + math.exp(-total))
        band = "low" if p < self.low_threshold else \
               "medium" if p < self.high_threshold else "high"
        return ScoreResult(probability=round(p, 6), band=band,
                           contributions=contribs, bias=self.bias)
