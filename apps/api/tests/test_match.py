import os

from cmahjong.ai.heuristic import decide
from cmahjong.orchestrate import drive
from cmahjong.rules.engine import new_match, reduce
from cmahjong.rules.tiles import INITIAL_POINTS
from cmahjong.rules.view import to_player_view


def play_until_stop(seed: bytes, rules: dict | None = None, limit: int = 400):
    state, events = new_match(rules, seed)
    state, more = drive(state)
    events.extend(more)
    steps = 0
    while state.phase not in ("between_hands", "completed") and steps < limit:
        view = to_player_view(state, 0)
        assert view["legal_actions"], state.phase
        action = decide(view)
        if action["type"] == "exchange":
            action = {"type": "exchange", "tiles": action["tiles"]}
        state, produced = reduce(state, 0, action)
        events.extend(produced)
        state, more = drive(state)
        events.extend(more)
        steps += 1
    return state, events, steps


def test_full_hand_conserves_tiles_and_points():
    state, events, steps = play_until_stop(os.urandom(32))
    assert state.phase in ("between_hands", "completed")
    assert sum(state.scores_hand) == 0
    assert sum(state.scores_game) == INITIAL_POINTS * 4
    assert steps < 400
    assert events


def test_bust_ends_match_and_new_match_restores_100():
    state, _ = new_match({"base_score": 1, "enable_exchange": False}, os.urandom(32))
    state.scores_game = [1, 100, 100, 199]
    # 让南家自摸一张平胡不现实。直接把账本打成东家付出超过 1 分。
    from cmahjong.rules.engine import _add_ledger, _bust

    events = []
    _add_ledger(state, 0, 1, 4, "pay.zimo", {"fan_raw": 3, "fan_charged": 3}, 3, 3)
    assert _bust(state, events)
    assert state.phase == "completed"
    assert state.end_reason == "bust"
    assert state.scores_game[0] <= 0
    assert sum(state.scores_game) == 400
    fresh, _ = new_match({"base_score": 1}, os.urandom(32))
    assert fresh.scores_game == [INITIAL_POINTS] * 4
