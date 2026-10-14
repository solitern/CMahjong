"""把权威状态投影成一个座位能看见的 PlayerView。"""

from __future__ import annotations

from cmahjong.rules.engine import State, legal_actions
from cmahjong.rules.tiles import INITIAL_POINTS


def to_player_view(state: State, seat: int, game_id: str = "", seq: int = 0) -> dict:
    dingque_public = state.phase not in ("exchanging", "dingque")
    dingque = {}
    for index in range(4):
        if dingque_public or index == seat:
            dingque[str(index)] = state.dingque[index]
        else:
            dingque[str(index)] = None
    wins = {}
    for index, win in enumerate(state.wins):
        wins[str(index)] = None if win is None else {
            "seat": index,
            "tile": win["tile"],
            "hand": list(win["hand"]),
            "melds": win["melds"],
            "fan_raw": win["fan_raw"],
            "fan_charged": win["fan_charged"],
            "points": win["points"],
            "patterns": win["patterns"],
            "additives": win["additives"],
            "win_kind": win["win_kind"],
        }
    revealed = None
    if state.phase in ("between_hands", "completed"):
        revealed = {str(i): list(state.hands[i]) for i in range(4)}
    actions = legal_actions(state, seat)
    view = {
        "game_id": game_id,
        "seq": seq,
        "ruleset_version": state.ruleset_version,
        "rules": state.rules,
        "hand_index": state.hand_index,
        "phase": state.phase,
        "self_seat": seat,
        "dealer": state.dealer,
        "turn": state.turn,
        "wall_remaining": len(state.wall),
        "must_hu": any(item["type"] == "hu" for item in actions) and not any(item["type"] == "pass" or item["type"] == "discard" for item in actions),
        "self_drawn_tile": state.drawn_this_turn[seat],
        "exchange_direction": state.exchange_direction,
        "dingque": dingque,
        "hand": list(state.hands[seat]),
        "melds": {str(i): state.melds[i] for i in range(4)},
        "discards": {str(i): state.discards[i] for i in range(4)},
        "wins": wins,
        "scores_hand": list(state.scores_hand),
        "scores_game": list(state.scores_game),
        "hand_folded": state.hand_folded,
        "initial_points": INITIAL_POINTS,
        "end_reason": state.end_reason,
        "ledger": [
            {
                "clause_id": entry["clause_id"],
                "from_seat": entry["from_seat"],
                "to_seat": entry["to_seat"],
                "amount": entry["amount"],
                "fan_raw": entry["fan_raw"],
                "fan_charged": entry["fan_charged"],
                "detail": entry["detail"],
            }
            for entry in state.ledger
        ],
        "ledger_scope": "hand",
        "legal_actions": actions,
        "pending_kind": None if state.pending is None else state.pending["kind"],
        "orchestration_paused": state.orchestration_paused,
        "hints": None,
        "policy_version": "heuristic-v1",
    }
    if revealed is not None:
        view["revealed_hands"] = revealed
    return view
