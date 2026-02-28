from app.models.common import GamePhase

PHASE_TOOL_MATRIX: dict[str, set[GamePhase]] = {
    "save_menu": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING},
    "closed_bid": {GamePhase.CLOSED_BID},
    "prepare_dish": {GamePhase.SERVING},
    "serve_dish": {GamePhase.SERVING},
    "create_market_entry": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING, GamePhase.SERVING},
    "execute_transaction": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING, GamePhase.SERVING},
    "delete_market_entry": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING, GamePhase.SERVING},
    "send_message": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING, GamePhase.SERVING},
    "update_restaurant_is_open": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING, GamePhase.SERVING},
    "restaurant_info": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING, GamePhase.SERVING, GamePhase.STOPPED},
    "get_meals": {GamePhase.SPEAKING, GamePhase.CLOSED_BID, GamePhase.WAITING, GamePhase.SERVING, GamePhase.STOPPED},
}

def is_tool_allowed(phase: GamePhase, tool_name: str) -> bool:
    allowed = PHASE_TOOL_MATRIX.get(tool_name, set())
    return phase in allowed
