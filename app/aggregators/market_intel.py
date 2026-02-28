import time
import statistics
from dataclasses import dataclass

from app.models.market import MarketSnapshot

@dataclass(frozen=True)
class IngredientMarketStats:
    ingredient: str
    best_buy_price: float | None
    best_sell_price: float | None
    median_price: float | None
    buy_volume: float
    sell_volume: float

@dataclass(frozen=True)
class MarketIntel:
    ts_ms: int
    per_ingredient: list[IngredientMarketStats]
    opportunities: list[dict]

def compute_market_intel(market: MarketSnapshot | None) -> MarketIntel | None:
    if not market:
        return None
    
    by_ingredient: dict[str, list] = {}
    for e in market.entries:
        if not e.ingredient:
            continue
        by_ingredient.setdefault(e.ingredient, []).append(e)
    
    all_prices = [e.price for e in market.entries if e.price is not None]
    p25 = sorted(all_prices)[int(len(all_prices) * 0.25)] if len(all_prices) >= 4 else None
    p75 = sorted(all_prices)[int(len(all_prices) * 0.75)] if len(all_prices) >= 4 else None
    
    stats_list = []
    opportunities = []
    
    for ingredient, entries in by_ingredient.items():
        sell_entries = [e for e in entries if e.side == "SELL" and e.price is not None]
        buy_entries = [e for e in entries if e.side == "BUY" and e.price is not None]
        
        best_buy = min(e.price for e in sell_entries) if sell_entries else None
        best_sell = max(e.price for e in buy_entries) if buy_entries else None
        
        all_prices_ingr = [e.price for e in entries if e.price is not None]
        median = statistics.median(all_prices_ingr) if all_prices_ingr else None
        
        buy_volume = sum(e.quantity or 0 for e in buy_entries)
        sell_volume = sum(e.quantity or 0 for e in sell_entries)
        
        stats = IngredientMarketStats(
            ingredient=ingredient,
            best_buy_price=best_buy,
            best_sell_price=best_sell,
            median_price=median,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
        )
        stats_list.append(stats)
        
        if best_buy is not None and p25 is not None and best_buy < p25:
            opportunities.append({"type": "cheap_supply", "ingredient": ingredient, "price": best_buy})
        if best_sell is not None and p75 is not None and best_sell > p75:
            opportunities.append({"type": "good_demand", "ingredient": ingredient, "price": best_sell})
    
    return MarketIntel(ts_ms=int(time.time() * 1000), per_ingredient=stats_list, opportunities=opportunities)
