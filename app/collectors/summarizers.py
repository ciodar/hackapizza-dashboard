import time
from typing import Any

from app.models.restaurant import RestaurantsOverview, RestaurantRow, RestaurantDetail, MenuSnapshot, MenuItem
from app.models.market import MarketSnapshot, MarketEntry
from app.models.meals import MealsSnapshot, MealRequest
from app.models.bids import BidHistorySnapshot, BidRow

def _ts() -> int:
    return int(time.time() * 1000)

def _first(d: dict, *keys: str) -> Any:
    """Return the first value from d whose key exists and whose value is not None."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None

def _float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return None

def _int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def summarize_restaurants(payload: Any) -> tuple[RestaurantsOverview | None, dict[str, Any]]:
    try:
        if not isinstance(payload, list):
            return None, {"parse_ok": False, "error": "expected list"}
        rows = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rid = _int(_first(item, "id", "restaurantId", "restaurant_id"))
            name = _first(item, "name", "restaurantName", "restaurant_name")
            balance = _float(_first(item, "balance", "money", "saldo"))
            reputation = _float(_first(item, "reputation", "reputazione"))
            is_open = _bool(_first(item, "is_open", "isOpen", "open"))
            rows.append(RestaurantRow(restaurant_id=rid, name=name, balance=balance, reputation=reputation, is_open=is_open, raw=item))
        ov = RestaurantsOverview(ts_ms=_ts(), restaurants=rows)
        balances = [r.balance for r in rows if r.balance is not None]
        top_balance = max(balances) if balances else None
        return ov, {"parse_ok": True, "count": len(rows), "top_balance": top_balance}
    except Exception as e:
        return None, {"parse_ok": False, "error": str(e)}

def summarize_restaurant_detail(payload: Any, restaurant_id: int) -> tuple[RestaurantDetail | None, dict[str, Any]]:
    try:
        if not isinstance(payload, dict):
            return None, {"parse_ok": False, "error": "expected dict"}
        balance = _float(_first(payload, "balance", "money", "saldo"))
        reputation = _float(_first(payload, "reputation", "reputazione"))
        is_open = _bool(_first(payload, "is_open", "isOpen", "open"))
        
        raw_inv = _first(payload, "inventory", "inventario", "ingredients") or {}
        # Parse JSON string if the DB column stores inventory as JSON text
        if isinstance(raw_inv, str):
            import json as _json
            try:
                raw_inv = _json.loads(raw_inv)
            except Exception:
                raw_inv = {}
        inventory: dict[str, float] = {}
        if isinstance(raw_inv, dict):
            for k, v in raw_inv.items():
                f = _float(v)
                if f is not None:
                    inventory[str(k)] = f
        elif isinstance(raw_inv, list):
            for item in raw_inv:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("ingredient") or item.get("nome")
                    qty = _float(item.get("quantity") or item.get("qty") or item.get("quantita"))
                    if name and qty is not None:
                        inventory[str(name)] = qty
        
        detail = RestaurantDetail(
            ts_ms=_ts(), restaurant_id=restaurant_id, balance=balance, reputation=reputation,
            is_open=is_open, inventory=inventory, raw=payload
        )
        return detail, {"parse_ok": True, "balance": balance, "reputation": reputation, "is_open": is_open,
                        "inventory_items": len(inventory), "inventory_total_qty": sum(inventory.values())}
    except Exception as e:
        return None, {"parse_ok": False, "error": str(e)}

def summarize_menu(payload: Any, restaurant_id: int) -> tuple[MenuSnapshot | None, dict[str, Any]]:
    try:
        if not isinstance(payload, list):
            return None, {"parse_ok": False, "error": "expected list"}
        items = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = _first(item, "name", "dish", "piatto", "nome")
            price = _float(_first(item, "price", "prezzo", "costo"))
            items.append(MenuItem(name=name, price=price, raw=item))
        snap = MenuSnapshot(ts_ms=_ts(), restaurant_id=restaurant_id, items=items)
        prices = [i.price for i in items if i.price is not None]
        return snap, {
            "parse_ok": True,
            "items_count": len(items),
            "avg_price": sum(prices) / len(prices) if prices else None,
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
        }
    except Exception as e:
        return None, {"parse_ok": False, "error": str(e)}

def summarize_market_entries(payload: Any) -> tuple[MarketSnapshot | None, dict[str, Any]]:
    try:
        if not isinstance(payload, list):
            return None, {"parse_ok": False, "error": "expected list"}
        entries = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            entry_id = _int(_first(item, "id", "entry_id", "entryId"))
            side = _first(item, "side", "type", "tipo")
            if side:
                side = str(side).upper()
            ingredient = _first(item, "ingredient", "ingredient_name", "ingrediente")
            if isinstance(ingredient, dict):
                ingredient = ingredient.get("name") or ingredient.get("nome") or str(ingredient)
            quantity = _float(_first(item, "quantity", "qty", "quantita"))
            price = _float(_first(item, "price", "prezzo"))
            owner_id = _int(_first(item, "owner_id", "ownerId", "restaurant_id"))
            entries.append(MarketEntry(entry_id=entry_id, side=side, ingredient=ingredient, quantity=quantity, price=price, owner_id=owner_id, raw=item))
        snap = MarketSnapshot(ts_ms=_ts(), entries=entries)
        buy_count = sum(1 for e in entries if e.side == "BUY")
        sell_count = sum(1 for e in entries if e.side == "SELL")
        return snap, {"parse_ok": True, "active_count": len(entries), "buy_count": buy_count, "sell_count": sell_count}
    except Exception as e:
        return None, {"parse_ok": False, "error": str(e)}

def summarize_meals(payload: Any, turn_id: int, restaurant_id: int) -> tuple[MealsSnapshot | None, dict[str, Any]]:
    try:
        if not isinstance(payload, list):
            return None, {"parse_ok": False, "error": "expected list"}
        meals = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            client_id = str(_first(item, "client_id", "clientId", "id") or "")
            client_name = _first(item, "client_name", "clientName", "name", "nome")
            order_text = _first(item, "order", "orderText", "order_text", "richiesta")
            executed = _bool(_first(item, "executed", "served", "servito"))
            raw_allergies = item.get("allergies") or []
            raw_intolerances = item.get("intolerances") or []
            # JSON columns may be returned as str (some MySQL drivers don't auto-parse)
            if isinstance(raw_allergies, str):
                import json as _json
                try:
                    raw_allergies = _json.loads(raw_allergies)
                except Exception:
                    raw_allergies = []
            if isinstance(raw_intolerances, str):
                import json as _json
                try:
                    raw_intolerances = _json.loads(raw_intolerances)
                except Exception:
                    raw_intolerances = []
            meals.append(MealRequest(
                client_id=client_id, client_name=client_name, order_text=order_text,
                executed=executed, raw=item,
                allergies=list(raw_allergies), intolerances=list(raw_intolerances),
            ))
        snap = MealsSnapshot(ts_ms=_ts(), turn_id=turn_id, restaurant_id=restaurant_id, meals=meals)
        total = len(meals)
        exec_count = sum(1 for m in meals if m.executed)
        pending = total - exec_count
        return snap, {"parse_ok": True, "total": total, "pending": pending, "executed": exec_count}
    except Exception as e:
        return None, {"parse_ok": False, "error": str(e)}

def summarize_bid_history(payload: Any, turn_id: int) -> tuple[BidHistorySnapshot | None, dict[str, Any]]:
    try:
        if not isinstance(payload, list):
            return None, {"parse_ok": False, "error": "expected list"}
        bids = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            # bid_history table uses ingredient_name + price (not ingredient + bid)
            ingredient = _first(item, "ingredient_name", "ingredient", "ingrediente")
            if isinstance(ingredient, dict):
                ingredient = ingredient.get("name") or ingredient.get("nome") or str(ingredient)
            bid = _float(_first(item, "price", "bid", "offer", "offerta"))
            quantity = _float(_first(item, "quantity", "qty", "quantita"))
            restaurant_id = _int(_first(item, "restaurant_id", "restaurantId"))
            bids.append(BidRow(ingredient=ingredient, bid=bid, quantity=quantity, restaurant_id=restaurant_id, raw=item))
        snap = BidHistorySnapshot(ts_ms=_ts(), turn_id=turn_id, bids=bids)
        return snap, {"parse_ok": True, "count": len(bids)}
    except Exception as e:
        return None, {"parse_ok": False, "error": str(e)}

def summarize_recipes(payload: Any) -> tuple[list[dict], dict[str, Any]]:
    try:
        if not isinstance(payload, list):
            return [], {"parse_ok": False, "error": "expected list"}
        return payload, {"parse_ok": True, "count": len(payload)}
    except Exception as e:
        return [], {"parse_ok": False, "error": str(e)}


def summarize_recipe_stats(payload: Any) -> tuple[list[dict], dict[str, Any]]:
    """Normalize recipe_stats rows from the DB."""
    try:
        if not isinstance(payload, list):
            return [], {"parse_ok": False, "error": "expected list"}
        result = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            result.append({
                "recipe_name": item.get("recipe_name") or item.get("name") or "",
                "prestige": _int(item.get("prestige")) or 0,
                "turn_id": _int(item.get("turn_id")),
                "num_requests": _int(item.get("num_requests")) or 0,
                "num_served": _int(item.get("num_served")) or 0,
                "avg_price": _float(item.get("avg_price")),
                "min_price": _float(item.get("min_price")),
                "max_price": _float(item.get("max_price")),
            })
        return result, {"parse_ok": True, "count": len(result)}
    except Exception as e:
        return [], {"parse_ok": False, "error": str(e)}


def summarize_ingredient_bid_stats(payload: Any) -> tuple[list[dict], dict[str, Any]]:
    """Normalize ingredient_bid_stats rows from the DB."""
    try:
        if not isinstance(payload, list):
            return [], {"parse_ok": False, "error": "expected list"}
        result = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            result.append({
                "ingredient_name": item.get("ingredient_name") or item.get("name") or "",
                "turn_id": _int(item.get("turn_id")),
                "avg_price_paid": _float(item.get("avg_price_paid")),
                "min_price_paid": _float(item.get("min_price_paid")),
                "max_price_paid": _float(item.get("max_price_paid")),
                "total_quantity": _int(item.get("total_quantity")) or 0,
            })
        return result, {"parse_ok": True, "count": len(result)}
    except Exception as e:
        return [], {"parse_ok": False, "error": str(e)}
