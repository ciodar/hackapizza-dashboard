import time
import statistics
from dataclasses import dataclass

from app.models.bids import BidHistorySnapshot

@dataclass(frozen=True)
class IngredientBidStats:
    ingredient: str
    min_bid: float | None
    median_bid: float | None
    max_bid: float | None
    sample_count: int

@dataclass(frozen=True)
class BidIntel:
    ts_ms: int
    per_ingredient: list[IngredientBidStats]

def compute_bid_intel(bid_history: BidHistorySnapshot | None) -> BidIntel | None:
    if not bid_history:
        return None
    
    by_ingredient: dict[str, list[float]] = {}
    for b in bid_history.bids:
        if b.ingredient and b.bid is not None:
            by_ingredient.setdefault(b.ingredient, []).append(b.bid)
    
    stats = []
    for ingredient, bids in by_ingredient.items():
        stats.append(IngredientBidStats(
            ingredient=ingredient,
            min_bid=min(bids) if bids else None,
            median_bid=statistics.median(bids) if bids else None,
            max_bid=max(bids) if bids else None,
            sample_count=len(bids),
        ))
    
    return BidIntel(ts_ms=int(time.time() * 1000), per_ingredient=stats)
