import time
from dataclasses import dataclass

from app.models.meals import MealsSnapshot

@dataclass(frozen=True)
class MealsKPI:
    ts_ms: int
    total: int
    pending: int
    executed: int
    execution_rate: float
    backlog_severity: str

def compute_meals_kpi(meals: MealsSnapshot | None) -> MealsKPI | None:
    if not meals:
        return None
    total = len(meals.meals)
    executed = sum(1 for m in meals.meals if m.executed)
    pending = total - executed
    rate = executed / total if total > 0 else 0.0
    
    if pending >= 10:
        severity = "crit"
    elif pending >= 5:
        severity = "warn"
    else:
        severity = "ok"
    
    return MealsKPI(
        ts_ms=int(time.time() * 1000), total=total, pending=pending,
        executed=executed, execution_rate=rate, backlog_severity=severity,
    )
