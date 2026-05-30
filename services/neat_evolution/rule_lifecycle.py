from enum import Enum

class RuleStatus(Enum):
    SHADOW = "shadow"
    PROMOTED = "promoted"
    RETIRED = "retired"

class RuleLifecycle:
    def __init__(self):
        self.rules: dict[str, RuleStatus] = {}

    def register(self, rule_id: str):
        self.rules[rule_id] = RuleStatus.SHADOW

    def promote(self, rule_id: str):
        self.rules[rule_id] = RuleStatus.PROMOTED

    def retire(self, rule_id: str):
        self.rules[rule_id] = RuleStatus.RETIRED

    def active_rules(self) -> list[str]:
        return [rid for rid, s in self.rules.items() if s == RuleStatus.PROMOTED]
