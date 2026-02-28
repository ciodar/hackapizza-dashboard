import time
from dataclasses import dataclass

from app.models.restaurant import RestaurantsOverview

@dataclass(frozen=True)
class RankingRow:
    rank: int
    restaurant_id: int | None
    name: str | None
    balance: float | None
    reputation: float | None
    is_open: bool | None

@dataclass(frozen=True)
class RankingSummary:
    ts_ms: int
    rows: list[RankingRow]
    my_rank: int | None
    delta_to_leader: float | None
    delta_to_next: float | None
    delta_to_prev: float | None

def compute_ranking(overview: RestaurantsOverview | None, my_restaurant_id: int) -> RankingSummary | None:
    if not overview or not overview.restaurants:
        return None
    
    sorted_rows = sorted(
        overview.restaurants,
        key=lambda r: (-(r.balance or 0), r.restaurant_id or 0)
    )
    
    rows = [
        RankingRow(
            rank=i + 1,
            restaurant_id=r.restaurant_id,
            name=r.name,
            balance=r.balance,
            reputation=r.reputation,
            is_open=r.is_open,
        )
        for i, r in enumerate(sorted_rows)
    ]
    
    my_row = next((r for r in rows if r.restaurant_id == my_restaurant_id), None)
    my_rank = my_row.rank if my_row else None
    my_balance = my_row.balance or 0 if my_row else 0
    
    leader_balance = rows[0].balance or 0 if rows else 0
    delta_to_leader = leader_balance - my_balance if my_rank != 1 else None
    
    delta_to_next = None
    delta_to_prev = None
    if my_rank and my_rank > 1:
        prev_row = rows[my_rank - 2]
        delta_to_prev = (prev_row.balance or 0) - my_balance
    if my_rank and my_rank < len(rows):
        next_row = rows[my_rank]
        delta_to_next = my_balance - (next_row.balance or 0)
    
    return RankingSummary(
        ts_ms=int(time.time() * 1000),
        rows=rows,
        my_rank=my_rank,
        delta_to_leader=delta_to_leader,
        delta_to_next=delta_to_next,
        delta_to_prev=delta_to_prev,
    )
