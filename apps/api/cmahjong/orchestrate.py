"""把人机走到下一次人类决策。reduce 只记账，不调用人机。"""

from __future__ import annotations

import time

from cmahjong.ai.heuristic import decide
from cmahjong.rules.engine import State, legal_actions, reduce
from cmahjong.rules.view import to_player_view

HUMAN = 0


def waiting_for_human(state: State) -> bool:
    if state.phase in ("between_hands", "completed"):
        return state.phase == "between_hands"
    actions = legal_actions(state, HUMAN)
    if not actions:
        return False
    if len(actions) == 1 and actions[0]["type"] == "pass":
        return False
    return True


def next_ai_seat(state: State) -> int | None:
    if state.phase in ("between_hands", "completed"):
        return None
    if state.pending:
        for seat, decision in state.pending["decisions"].items():
            if decision is None and seat != HUMAN:
                return seat
        if state.pending["decisions"].get(HUMAN) is None:
            actions = legal_actions(state, HUMAN)
            if len(actions) == 1 and actions[0]["type"] == "pass":
                return HUMAN
        return None
    if state.phase == "turn_discard" and state.turn is not None and state.turn != HUMAN and state.wins[state.turn] is None:
        return state.turn
    if state.phase == "turn_discard" and state.turn == HUMAN:
        actions = legal_actions(state, HUMAN)
        if len(actions) == 1 and actions[0]["type"] == "pass":
            return HUMAN
    return None


def drive(state: State, max_steps: int = 256, max_seconds: float = 1.5) -> tuple[State, list[dict]]:
    events: list[dict] = []
    started = time.perf_counter()
    steps = 0
    while steps < max_steps and time.perf_counter() - started < max_seconds:
        if state.phase in ("completed",) or (state.phase == "between_hands" and not False):
            state.orchestration_paused = False
            break
        seat = next_ai_seat(state)
        if seat is None:
            state.orchestration_paused = False
            break
        if seat == HUMAN:
            action = legal_actions(state, HUMAN)[0]
        else:
            action = decide(to_player_view(state, seat))
        state, produced = reduce(state, seat, action)
        events.extend(produced)
        steps += 1
    else:
        if state.phase not in ("between_hands", "completed"):
            state.orchestration_paused = True
    return state, events
