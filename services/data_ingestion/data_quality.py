import time
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class QualityMetrics:
    total: int = 0
    errors: int = 0
    last_ts: float = field(default_factory=time.time)

    def record(self, ok: bool):
        self.total += 1
        if not ok:
            self.errors += 1
        self.last_ts = time.time()

    @property
    def score(self) -> float:
        if self.total == 0:
            return 1.0
        return 1.0 - (self.errors / self.total)

    @property
    def staleness_seconds(self) -> float:
        return time.time() - self.last_ts

quality_registry: Dict[str, QualityMetrics] = {}

def get_quality(stream: str) -> QualityMetrics:
    if stream not in quality_registry:
        quality_registry[stream] = QualityMetrics()
    return quality_registry[stream]
