import time
from typing import Any

from app.models.restaurant import RestaurantsOverview, RestaurantRow, RestaurantDetail, MenuSnapshot, MenuItem
from app.models.market import MarketSnapshot, MarketEntry
from app.models.meals import MealsSnapshot, MealRequest
from app.models.bids import BidHistorySnapshot, BidRow

def _ts() -> int:
    return int(time.time() * 1000)

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
            rid = _int(item.get("id") or item.get("restaurantId") or item.get("restaurant_id"))
            name = item.get("name") or item.get("restaurantName") or item.get("restaurant_name")
            balance = _float(item.get("balance") or item.get("money") or item.get("saldo"))
            reputation = _float(item.get("reputation") or item.get("reputazione"))
            is_open = _bool(item.get("is_open") or item.get("isOpen") or item.get("open"))
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
        balance = _float(payload.get("balance") or payload.get("money") or payload.get("saldo"))
        reputation = _float(payload.get("reputation") or payload.get("reputazione"))
        is_open = _bool(payload.get("is_open") or payload.get("isOpen") or payload.get("open"))
        
        raw_inv = payload.get("inventory") or payload.get("inventario") or payload.get("ingredients") or {}
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
            name = item.get("name") or item.get("dish") or item.get("piatto") or item.get("nome")
            price = _float(item.get("price") or item.get("prezzo") or item.get("costo"))
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
            entry_id = _int(item.get("id") or item.get("entry_id") or item.get("entryId"))
            side = item.get("side") or item.get("type") or item.get("tipo")
            if side:
                side = str(side).upper()
            ingredient = item.get("ingredient") or item.get("ingredient_name") or item.get("ingrediente")
            if isinstance(ingredient, dict):
                ingredient = ingredient.get("name") or ingredient.get("nome") or str(ingredient)
            quantity = _float(item.get("quantity") or item.get("qty") or item.get("quantita"))
            price = _float(item.get("price") or item.get("prezzo"))
            owner_id = _int(item.get("owner_id") or item.get("ownerId") or item.get("restaurant_id"))
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
            client_id = str(item.get("client_id") or item.get("clientId") or item.get("id") or "")
            client_name = item.get("client_name") or item.get("clientName") or item.get("name") or item.get("nome")
            order_text = item.get("order") or item.get("orderText") or item.get("order_text") or item.get("richiesta")
            executed = _bool(item.get("executed") or item.get("served") or item.get("servito"))
            meals.append(MealRequest(client_id=client_id, client_name=client_name, order_text=order_text, executed=executed, raw=item))
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
            ingredient = item.get("ingredient") or item.get("ingrediente")
            bid = _float(item.get("bid") or item.get("offer") or item.get("offerta"))
            quantity = _float(item.get("quantity") or item.get("qty") or item.get("quantita"))
            restaurant_id = _int(item.get("restaurant_id") or item.get("restaurantId"))
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
