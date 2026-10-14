"""行牌、刮风下雨、血战结算。每人从 100 分起，有人到 0 分或以下则整局结束。"""

from __future__ import annotations

import copy
import hashlib
import hmac
import os
from dataclasses import dataclass

from cmahjong.rules.tiles import (
    INITIAL_POINTS,
    SUITS,
    counts_of,
    key_of,
    next_seat,
    rank_of,
    suit_of,
    tile_id,
)
from cmahjong.rules.win import FanOut, Meld, RuleError, evaluate, is_winning_shape, score_of

DIRECTIONS = ("to_next", "to_prev", "to_across")
DIR_STEP = {"to_next": 1, "to_prev": 3, "to_across": 2}


@dataclass
class State:
    ruleset_version: str
    rules: dict
    seed_hex: str
    hand_index: int
    dealer: int
    wall: list[int]
    hands: list[list[int]]
    melds: list[list[dict]]
    discards: list[list[dict]]
    dingque: list[str | None]
    exchange_direction: str | None
    phase: str
    turn: int | None
    wins: list[dict | None]
    pass_hu: list[bool]
    after_kong: list[bool]
    last_kong_receipt_id: list[str | None]
    drawn_this_turn: list[int | None]
    draws_taken: list[int]
    any_kong_or_pong: bool
    dealer_has_discarded: bool
    must_hu: bool
    pending: dict | None
    pending_ba_kong: dict | None
    kong_receipts: list[dict]
    ledger: list[dict]
    scores_hand: list[int]
    scores_game: list[int]
    hand_folded: bool
    hu_events: list[dict]
    end_reason: str | None = None
    orchestration_paused: bool = False
    receipt_seq: int = 0

    def to_dict(self) -> dict:
        return copy.deepcopy(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> State:
        raw = copy.deepcopy(data)
        pending = raw.get("pending")
        if pending and isinstance(pending.get("decisions"), dict):
            pending["decisions"] = {int(seat): action for seat, action in pending["decisions"].items()}
        return cls(**raw)


def _rng_bytes(seed: bytes, counter: list[int], nbytes: int = 8) -> bytes:
    out = b""
    while len(out) < nbytes:
        out += hmac.new(seed, counter[0].to_bytes(4, "big"), hashlib.sha256).digest()
        counter[0] += 1
    return out[:nbytes]


def _randbelow(seed: bytes, counter: list[int], limit: int) -> int:
    cap = (1 << 64) - ((1 << 64) % limit)
    while True:
        val = int.from_bytes(_rng_bytes(seed, counter), "big")
        if val < cap:
            return val % limit


def _shuffle(seed: bytes) -> tuple[list[int], int, str]:
    counter = [0]
    items = list(range(108))
    for i in range(107, 0, -1):
        j = _randbelow(seed, counter, i + 1)
        items[i], items[j] = items[j], items[i]
    dealer = _randbelow(seed, counter, 4)
    direction = DIRECTIONS[_randbelow(seed, counter, 3)]
    return items, dealer, direction


def hand_seed(master_hex: str, hand_index: int) -> bytes:
    return hmac.new(bytes.fromhex(master_hex), f"hand:{hand_index}".encode(), hashlib.sha256).digest()


def new_match(rules: dict | None = None, seed: bytes | None = None) -> tuple[State, list[dict]]:
    rules = {
        "base_score": 1,
        "fan_cap": 5,
        "enable_exchange": True,
        "enable_jingoudiao": False,
        "show_ting_hint": False,
        **(rules or {}),
    }
    if not 1 <= int(rules["base_score"]) <= 10000:
        raise RuleError("底分要在 1 到 10000 之间", "invalid_rules")
    if seed is None:
        seed = os.urandom(32)
    master = seed.hex()
    state = State(
        ruleset_version="chengdu-xz-1",
        rules=rules,
        seed_hex=master,
        hand_index=0,
        dealer=0,
        wall=[],
        hands=[[] for _ in range(4)],
        melds=[[] for _ in range(4)],
        discards=[[] for _ in range(4)],
        dingque=[None] * 4,
        exchange_direction=None,
        phase="exchanging",
        turn=None,
        wins=[None] * 4,
        pass_hu=[False] * 4,
        after_kong=[False] * 4,
        last_kong_receipt_id=[None] * 4,
        drawn_this_turn=[None] * 4,
        draws_taken=[0] * 4,
        any_kong_or_pong=False,
        dealer_has_discarded=False,
        must_hu=False,
        pending=None,
        pending_ba_kong=None,
        kong_receipts=[],
        ledger=[],
        scores_hand=[0, 0, 0, 0],
        scores_game=[INITIAL_POINTS] * 4,
        hand_folded=False,
        hu_events=[],
    )
    events: list[dict] = []
    _deal(state, events, dealer=None)
    return state, events


def _deal(state: State, events: list[dict], dealer: int | None) -> None:
    seed = hand_seed(state.seed_hex, state.hand_index)
    wall, rolled_dealer, direction = _shuffle(seed)
    if dealer is None:
        dealer = rolled_dealer
    state.dealer = dealer
    state.wall = wall
    state.hands = [[], [], [], []]
    for _ in range(13):
        for seat in range(4):
            state.hands[seat].append(state.wall.pop(0))
    state.hands[dealer].append(state.wall.pop(0))
    for seat in range(4):
        state.hands[seat].sort()
    events.append(
        {
            "type": "deal",
            "actor": None,
            "payload": {
                "seed_hex": seed.hex(),
                "dealer": dealer,
                "wall": list(state.wall),
                "hands": [list(h) for h in state.hands],
            },
        }
    )
    if state.rules.get("enable_exchange", True):
        state.exchange_direction = direction
        state.phase = "exchanging"
        events.append({"type": "exchange_direction", "actor": None, "payload": {"direction": direction}})
        _open_window(state, "exchange", None, None, events)
    else:
        state.exchange_direction = None
        state.phase = "dingque"
        _open_window(state, "dingque", None, None, events)


def reduce(state: State, seat: int, action: dict) -> tuple[State, list[dict]]:
    nxt = copy.deepcopy(state)
    events: list[dict] = []
    _apply(nxt, seat, action, events)
    _assert_state(nxt)
    return nxt, events


def _apply(state: State, seat: int, action: dict, events: list[dict]) -> None:
    kind = action.get("type")
    if state.phase == "completed":
        raise RuleError("这局已经结束", "illegal_action")
    if state.phase == "between_hands":
        if seat != 0:
            raise RuleError("只有你能开始下一盘或结束", "illegal_action")
        if kind == "next_hand":
            _next_hand(state, events)
            return
        if kind == "end_game":
            state.phase = "completed"
            state.end_reason = "player_end"
            state.turn = None
            events.append({"type": "match_end", "actor": 0, "payload": {"reason": "player_end", "scores": list(state.scores_game)}})
            return
        raise RuleError("现在只能再来一盘或结束", "illegal_action")
    if state.pending and state.pending["decisions"].get(seat, "absent") is None:
        _submit_window(state, seat, action, events)
        return
    if state.phase == "turn_discard" and state.turn == seat and state.wins[seat] is None:
        _act_discard_phase(state, seat, action, events)
        return
    raise RuleError("还没轮到你", "illegal_action", "rule.win_priority")


def legal_actions(state: State, seat: int) -> list[dict]:
    if state.phase == "completed":
        return []
    if state.phase == "between_hands":
        return [{"type": "next_hand"}, {"type": "end_game"}] if seat == 0 else []
    if state.pending and seat in state.pending["decisions"] and state.pending["decisions"][seat] is None:
        return _window_actions(state, seat)
    if state.phase == "turn_discard" and state.turn == seat and state.wins[seat] is None:
        return _discard_actions(state, seat)
    return []


def _window_actions(state: State, seat: int) -> list[dict]:
    kind = state.pending["kind"]
    if kind == "exchange":
        return [{"type": "exchange"}]
    if kind == "dingque":
        return [{"type": "dingque", "suit": suit} for suit in SUITS]
    tile = state.pending["tile_id"]
    actions: list[dict] = []
    can_hu = _can_hu_tile(state, seat, tile, from_discard=True)
    forced = bool(state.must_hu and can_hu)
    if can_hu:
        actions.append({"type": "hu"})
    if not forced and kind == "claims":
        if _can_zhi_kong(state, seat, tile):
            actions.append({"type": "kong", "tile": tile, "kong_kind": "zhi"})
        if _can_pong(state, seat, tile):
            actions.append({"type": "pong"})
    if not forced:
        actions.append({"type": "pass"})
    return actions or [{"type": "pass"}]


def _discard_actions(state: State, seat: int) -> list[dict]:
    hand = state.hands[seat]
    if _can_zimo(state, seat) and state.must_hu:
        return [{"type": "hu"}]
    actions: list[dict] = []
    if _can_zimo(state, seat):
        actions.append({"type": "hu"})
    if not _has_que(state, seat) and state.wall:
        for key, tiles in _groups(hand).items():
            if len(tiles) == 4:
                actions.append({"type": "kong", "tile": tiles[0], "kong_kind": "an"})
        for meld in state.melds[seat]:
            if meld["kind"] == "pong":
                extra = [t for t in hand if key_of(t) == key_of(meld["tiles"][0])]
                if extra:
                    actions.append({"type": "kong", "tile": extra[0], "kong_kind": "ba"})
    que = state.dingque[seat]
    if _has_que(state, seat):
        options = [t for t in hand if suit_of(t) == que]
    else:
        options = list(hand)
    seen: set[int] = set()
    for tile in options:
        if tile in seen:
            continue
        seen.add(tile)
        actions.append({"type": "discard", "tile": tile})
    return actions


def _act_discard_phase(state: State, seat: int, action: dict, events: list[dict]) -> None:
    allowed = _discard_actions(state, seat)
    if not _same_action(action, allowed):
        raise RuleError("这步不能这么走", "illegal_action", "rule.must_discard_que")
    kind = action["type"]
    if kind == "hu":
        _zimo(state, seat, events)
        return
    if kind == "discard":
        _discard(state, seat, int(action["tile"]), events)
        return
    if kind == "kong":
        if action["kong_kind"] == "an":
            _an_kong(state, seat, int(action["tile"]), events)
        else:
            _declare_ba(state, seat, int(action["tile"]), events)
        return
    raise RuleError("这步不能这么走", "illegal_action")


def _submit_window(state: State, seat: int, action: dict, events: list[dict]) -> None:
    allowed = _window_actions(state, seat)
    if state.pending["kind"] == "exchange":
        tiles = list(action.get("tiles") or [])
        if action.get("type") != "exchange" or not _valid_exchange(state.hands[seat], tiles):
            raise RuleError("要交同一花色的 3 张", "illegal_action")
        state.pending["decisions"][seat] = {"type": "exchange", "tiles": tiles}
        events.append({"type": "exchange_submit", "actor": seat, "payload": {"seat": seat, "tiles": tiles}})
    elif state.pending["kind"] == "dingque":
        suit = action.get("suit")
        if action.get("type") != "dingque" or suit not in SUITS:
            raise RuleError("要选一门缺", "illegal_action")
        state.pending["decisions"][seat] = {"type": "dingque", "suit": suit}
        events.append({"type": "dingque_submit", "actor": seat, "payload": {"seat": seat, "suit": suit}})
    else:
        if not _same_action(action, allowed):
            raise RuleError("这步不能这么走", "illegal_action")
        stored = dict(action)
        stored["could_hu"] = any(item["type"] == "hu" for item in allowed)
        state.pending["decisions"][seat] = stored
        events.append(
            {
                "type": "pass" if action["type"] == "pass" else action["type"],
                "actor": seat,
                "payload": {"seat": seat, "set_guoshui": stored["could_hu"] and action["type"] != "hu"},
            }
        )
    if all(value is not None for value in state.pending["decisions"].values()):
        _resolve_window(state, events)


def _open_window(state: State, kind: str, source: int | None, tile: int | None, events: list[dict]) -> None:
    if kind in ("exchange", "dingque"):
        seats = list(range(4))
    else:
        seats = [s for s in range(4) if s != source and state.wins[s] is None]
    state.pending = {"kind": kind, "decisions": {s: None for s in seats}, "source_seat": source, "tile_id": tile}
    if kind == "claims":
        state.phase = "await_claims"
    elif kind == "rob":
        state.phase = "await_rob"
    for seat in seats:
        actions = _window_actions(state, seat)
        only_pass = len(actions) == 1 and actions[0]["type"] == "pass"
        if only_pass:
            state.pending["decisions"][seat] = {"type": "pass", "could_hu": False}
    if all(value is not None for value in state.pending["decisions"].values()):
        _resolve_window(state, events)


def _resolve_window(state: State, events: list[dict]) -> None:
    pending = state.pending
    assert pending is not None
    kind = pending["kind"]
    if kind == "exchange":
        _resolve_exchange(state, events)
        return
    if kind == "dingque":
        _resolve_dingque(state, events)
        return
    if kind == "rob":
        _resolve_rob(state, events)
        return
    _resolve_claims(state, events)


def _resolve_exchange(state: State, events: list[dict]) -> None:
    offers = {seat: list(action["tiles"]) for seat, action in state.pending["decisions"].items()}
    step = DIR_STEP[state.exchange_direction]
    moved: dict[int, list[int]] = {s: [] for s in range(4)}
    for seat, tiles in offers.items():
        for tile in tiles:
            state.hands[seat].remove(tile)
        moved[(seat + step) % 4].extend(tiles)
    for seat, tiles in moved.items():
        state.hands[seat].extend(tiles)
        state.hands[seat].sort()
    events.append({"type": "exchange_resolve", "actor": None, "payload": {"offers": offers, "received": moved}})
    state.pending = None
    state.phase = "dingque"
    _open_window(state, "dingque", None, None, events)


def _resolve_dingque(state: State, events: list[dict]) -> None:
    for seat, action in state.pending["decisions"].items():
        state.dingque[seat] = action["suit"]
    events.append({"type": "dingque_reveal", "actor": None, "payload": {"dingque": list(state.dingque)}})
    state.pending = None
    state.phase = "turn_discard"
    state.turn = state.dealer
    state.must_hu = False
    state.dealer_has_discarded = False


def _resolve_claims(state: State, events: list[dict]) -> None:
    pending = state.pending
    source = pending["source_seat"]
    tile = pending["tile_id"]
    decisions = pending["decisions"]
    hu_seats = [s for s, action in decisions.items() if action and action["type"] == "hu"]
    for seat, action in decisions.items():
        if action and action.get("could_hu") and seat not in hu_seats:
            state.pass_hu[seat] = True
    state.pending = None
    if hu_seats:
        _dianpao(state, source, tile, hu_seats, "dianpao", events)
        return
    kong_seat = next((s for s, action in decisions.items() if action and action["type"] == "kong"), None)
    if kong_seat is not None:
        _close_after_kong(state, source)
        _zhi_kong(state, kong_seat, source, tile, events)
        return
    pongers = [s for s, action in decisions.items() if action and action["type"] == "pong"]
    if pongers:
        chosen = min(pongers, key=lambda s: (s - source) % 4)
        _close_after_kong(state, source)
        _pong(state, chosen, source, tile, events)
        return
    _close_after_kong(state, source)
    _draw_next(state, next_seat(source), events)


def _resolve_rob(state: State, events: list[dict]) -> None:
    pending = state.pending
    seat = state.pending_ba_kong["seat"]
    tile = state.pending_ba_kong["tile_id"]
    timely = state.pending_ba_kong["timely"]
    decisions = pending["decisions"]
    hu_seats = [s for s, action in decisions.items() if action and action["type"] == "hu"]
    for owner, action in decisions.items():
        if action and action.get("could_hu") and owner not in hu_seats:
            state.pass_hu[owner] = True
    state.pending = None
    if hu_seats:
        state.discards[seat].append({"tile": tile, "claimed_by": []})
        state.pending_ba_kong = None
        events.append({"type": "kong_cancel", "actor": seat, "payload": {"tile_id": tile, "seat": seat}})
        _dianpao(state, seat, tile, hu_seats, "qianggang", events)
        return
    meld = next(m for m in state.melds[seat] if m["kind"] == "pong" and key_of(m["tiles"][0]) == key_of(tile))
    meld["kind"] = "ba_kong"
    meld["tiles"] = list(meld["tiles"]) + [tile]
    state.pending_ba_kong = None
    state.any_kong_or_pong = True
    state.drawn_this_turn[seat] = None
    gross = 0
    if timely:
        gross = _kong_pay(state, seat, "kong.gua_feng_ba", 1, payer=None, events=events)
    state.after_kong[seat] = True
    events.append(
        {
            "type": "kong",
            "actor": seat,
            "payload": {"seat": seat, "kind": "ba", "tiles": list(meld["tiles"]), "timely": timely, "gross": gross},
        }
    )
    if _bust(state, events):
        return
    _supplement(state, seat, events)


def _discard(state: State, seat: int, tile: int, events: list[dict]) -> None:
    state.hands[seat].remove(tile)
    state.drawn_this_turn[seat] = None
    if seat == state.dealer:
        state.dealer_has_discarded = True
    state.discards[seat].append({"tile": tile, "claimed_by": []})
    state.must_hu = len(state.wall) <= 4
    state.turn = None
    events.append(
        {
            "type": "discard",
            "actor": seat,
            "payload": {
                "seat": seat,
                "tile": tile,
                "wall_remaining": len(state.wall),
                "after_kong": state.after_kong[seat],
                "receipt_id": state.last_kong_receipt_id[seat],
            },
        }
    )
    _open_window(state, "claims", seat, tile, events)


def _zimo(state: State, seat: int, events: list[dict]) -> None:
    tianhu = (
        seat == state.dealer
        and not state.dealer_has_discarded
        and state.draws_taken[seat] == 0
        and not state.any_kong_or_pong
    )
    dihu = (
        seat != state.dealer
        and state.draws_taken[seat] == 1
        and not state.any_kong_or_pong
        and not state.after_kong[seat]
    )
    fan = evaluate(
        state.hands[seat],
        _melds(state, seat),
        que=state.dingque[seat],
        base_score=state.rules["base_score"],
        enable_jingoudiao=bool(state.rules.get("enable_jingoudiao")),
        win_kind="zimo",
        after_kong=state.after_kong[seat],
        wall_after_draw=len(state.wall) if state.draws_taken[seat] else None,
        tianhu=tianhu,
        dihu=dihu,
    )
    if fan is None:
        raise RuleError("这手不能胡", "illegal_action", "rule.que_not_in_win")
    winners_before = sum(w is not None for w in state.wins)
    _record_win(state, seat, seat, state.drawn_this_turn[seat], fan, "zimo", events, payers=_active_except(state, seat))
    state.after_kong[seat] = False
    if _bust(state, events):
        return
    if winners_before + 1 >= 3:
        _settle_hand(state, "three_winners", events)
        return
    _draw_next(state, next_seat(seat), events)


def _dianpao(state: State, source: int, tile: int, hu_seats: list[int], win_kind: str, events: list[dict]) -> None:
    gangpao = win_kind == "dianpao" and state.after_kong[source]
    wins_payload = []
    for seat in sorted(hu_seats, key=lambda s: (s - source) % 4):
        logical = list(state.hands[seat]) + [tile]
        fan = evaluate(
            state.hands[seat],
            _melds(state, seat),
            que=state.dingque[seat],
            base_score=state.rules["base_score"],
            enable_jingoudiao=bool(state.rules.get("enable_jingoudiao")),
            win_kind="qianggang" if win_kind == "qianggang" else "dianpao",
            after_kong=gangpao,
            logical_concealed=logical,
        )
        if fan is None:
            raise RuleError("这手不能胡", "illegal_action")
        _pay_one(state, source, seat, fan, "pay.dianpao", tile, win_kind)
        _mark_win(state, seat, tile, fan, win_kind, include_tile_in_hand=False)
        wins_payload.append(_win_brief(seat, fan, win_kind))
    river = state.discards[source][-1]
    river["claimed_by"] = list(hu_seats)
    if gangpao:
        _transfer(state, source, hu_seats, events)
    state.after_kong[source] = False
    state.last_kong_receipt_id[source] = None
    events.append(
        {
            "type": "hu",
            "actor": source,
            "payload": {"provider_seat": source, "tile": tile, "wins": wins_payload, "win_kind": win_kind},
        }
    )
    state.hu_events.append({"provider": source, "seats": list(hu_seats)})
    if _bust(state, events):
        return
    if sum(w is not None for w in state.wins) >= 3:
        _settle_hand(state, "three_winners", events)
        return
    _draw_next(state, next_seat(source), events)


def _record_win(state: State, seat: int, provider: int, tile: int | None, fan: FanOut, win_kind: str, events: list[dict], payers: list[int]) -> None:
    for payer in payers:
        _pay_one(state, payer, seat, fan, "pay.zimo", tile, win_kind)
    _mark_win(state, seat, tile, fan, win_kind, include_tile_in_hand=True)
    events.append(
        {
            "type": "hu",
            "actor": seat,
            "payload": {
                "provider_seat": provider,
                "tile": tile,
                "wins": [_win_brief(seat, fan, win_kind)],
                "win_kind": win_kind,
            },
        }
    )
    state.hu_events.append({"provider": provider, "seats": [seat]})


def _mark_win(state: State, seat: int, tile: int | None, fan: FanOut, win_kind: str, include_tile_in_hand: bool) -> None:
    state.wins[seat] = {
        "seat": seat,
        "tile": tile,
        "hand": list(state.hands[seat]),
        "melds": copy.deepcopy(state.melds[seat]),
        "fan_raw": fan.fan_raw,
        "fan_charged": fan.fan_charged,
        "points": fan.points,
        "patterns": list(fan.patterns),
        "additives": list(fan.additives),
        "win_kind": win_kind,
        "include_tile": include_tile_in_hand,
    }


def _win_brief(seat: int, fan: FanOut, win_kind: str) -> dict:
    return {
        "seat": seat,
        "fan_raw": fan.fan_raw,
        "fan_charged": fan.fan_charged,
        "points": fan.points,
        "pattern_ids": list(fan.patterns),
        "additives": list(fan.additives),
        "win_kind": win_kind,
    }


def _pay_one(state: State, frm: int, to: int, fan: FanOut, clause: str, tile: int | None, win_kind: str) -> None:
    _add_ledger(
        state,
        frm,
        to,
        fan.points,
        clause,
        {
            "patterns": list(fan.patterns),
            "additives": list(fan.additives),
            "tile": tile,
            "win_kind": win_kind,
            "fan_raw": fan.fan_raw,
            "fan_charged": fan.fan_charged,
        },
        fan.fan_raw,
        fan.fan_charged,
    )


def _an_kong(state: State, seat: int, tile: int, events: list[dict]) -> None:
    group = [t for t in state.hands[seat] if key_of(t) == key_of(tile)]
    if len(group) != 4 or not state.wall:
        raise RuleError("现在不能暗杠", "illegal_action")
    for item in group:
        state.hands[seat].remove(item)
    state.melds[seat].append({"kind": "an_kong", "tiles": group, "from_seat": seat})
    state.any_kong_or_pong = True
    gross = _kong_pay(state, seat, "kong.xia_yu", 2, payer=None, events=events)
    state.after_kong[seat] = True
    state.drawn_this_turn[seat] = None
    events.append({"type": "kong", "actor": seat, "payload": {"seat": seat, "kind": "an", "tiles": group, "timely": True, "gross": gross}})
    if _bust(state, events):
        return
    _supplement(state, seat, events)


def _declare_ba(state: State, seat: int, tile: int, events: list[dict]) -> None:
    if tile not in state.hands[seat] or not state.wall:
        raise RuleError("现在不能巴杠", "illegal_action")
    state.hands[seat].remove(tile)
    timely = state.drawn_this_turn[seat] == tile
    state.pending_ba_kong = {"seat": seat, "tile_id": tile, "timely": timely}
    state.must_hu = len(state.wall) <= 4
    state.turn = None
    events.append({"type": "ba_declare", "actor": seat, "payload": {"seat": seat, "tile": tile, "timely": timely}})
    _open_window(state, "rob", seat, tile, events)


def _zhi_kong(state: State, seat: int, source: int, tile: int, events: list[dict]) -> None:
    group = [t for t in state.hands[seat] if key_of(t) == key_of(tile)]
    if len(group) < 3:
        raise RuleError("现在不能直杠", "illegal_action")
    use = group[:3]
    for item in use:
        state.hands[seat].remove(item)
    state.discards[source].pop()
    tiles = use + [tile]
    state.melds[seat].append({"kind": "zhi_kong", "tiles": tiles, "from_seat": source})
    state.any_kong_or_pong = True
    gross = _kong_pay(state, seat, "kong.gua_feng_zhi", 2, payer=source, events=events)
    state.after_kong[seat] = True
    state.drawn_this_turn[seat] = None
    events.append(
        {
            "type": "kong",
            "actor": seat,
            "payload": {"seat": seat, "from_seat": source, "kind": "zhi", "tiles": tiles, "timely": True, "gross": gross},
        }
    )
    if _bust(state, events):
        return
    _supplement(state, seat, events)


def _pong(state: State, seat: int, source: int, tile: int, events: list[dict]) -> None:
    group = [t for t in state.hands[seat] if key_of(t) == key_of(tile)]
    use = group[:2]
    for item in use:
        state.hands[seat].remove(item)
    state.discards[source].pop()
    state.melds[seat].append({"kind": "pong", "tiles": use + [tile], "from_seat": source})
    state.any_kong_or_pong = True
    state.drawn_this_turn[seat] = None
    state.after_kong[seat] = False
    state.phase = "turn_discard"
    state.turn = seat
    state.must_hu = False
    events.append({"type": "pong", "actor": seat, "payload": {"seat": seat, "from_seat": source, "tiles": use + [tile]}})


def _kong_pay(state: State, seat: int, clause: str, each: int, payer: int | None, events: list[dict]) -> int:
    payments: list[tuple[int, int]] = []
    if payer is None:
        payers = _active_except(state, seat)
        for other in payers:
            payments.append((other, each))
    else:
        if state.wins[payer] is None:
            payments.append((payer, each))
    gross = 0
    for frm, amount in payments:
        _add_ledger(state, frm, seat, amount, clause, {"kong": clause})
        gross += amount
    if gross:
        state.receipt_seq += 1
        receipt_id = f"k{state.hand_index}-{state.receipt_seq}"
        state.kong_receipts.append(
            {
                "receipt_id": receipt_id,
                "seat": seat,
                "clause_id": clause,
                "gross": gross,
                "payments": payments,
                "transferred": 0,
                "refunded": False,
            }
        )
        state.last_kong_receipt_id[seat] = receipt_id
    else:
        state.last_kong_receipt_id[seat] = None
    return gross


def _transfer(state: State, seat: int, winners: list[int], events: list[dict]) -> None:
    receipt_id = state.last_kong_receipt_id[seat]
    if not receipt_id:
        return
    receipt = next(item for item in state.kong_receipts if item["receipt_id"] == receipt_id)
    gross = receipt["gross"]
    if gross <= 0:
        return
    for winner in winners:
        _add_ledger(state, seat, winner, gross, "pay.hujiao_zhuanyi", {"receipt_id": receipt_id})
    receipt["transferred"] += gross * len(winners)
    events.append({"type": "ledger", "actor": seat, "payload": {"clause": "pay.hujiao_zhuanyi", "gross": gross, "n": len(winners)}})


def _supplement(state: State, seat: int, events: list[dict]) -> None:
    if not state.wall:
        _settle_hand(state, "wall", events)
        return
    _take_draw(state, seat, events, supplement=True)


def _draw_next(state: State, start: int, events: list[dict]) -> None:
    seat = _next_active(state, start)
    if seat is None or sum(w is not None for w in state.wins) >= 3:
        _settle_hand(state, "three_winners", events)
        return
    if not state.wall:
        _settle_hand(state, "wall", events)
        return
    _take_draw(state, seat, events, supplement=False)


def _take_draw(state: State, seat: int, events: list[dict], supplement: bool) -> None:
    wall_before = len(state.wall)
    tile = state.wall.pop(0)
    state.hands[seat].append(tile)
    state.draws_taken[seat] += 1
    state.pass_hu[seat] = False
    state.drawn_this_turn[seat] = tile
    state.phase = "turn_discard"
    state.turn = seat
    state.pending = None
    can = _can_zimo(state, seat)
    state.must_hu = wall_before <= 4 and can
    events.append(
        {
            "type": "draw",
            "actor": seat,
            "payload": {
                "seat": seat,
                "tile": tile,
                "wall_before": wall_before,
                "wall_remaining": len(state.wall),
                "supplement": supplement,
                "cleared_guoshui": True,
                "must_hu": state.must_hu,
            },
        }
    )


def _settle_hand(state: State, reason: str, events: list[dict]) -> None:
    if state.phase in ("between_hands", "completed") and state.hand_folded:
        return
    active = [s for s in range(4) if state.wins[s] is None]
    huazhu = [s for s in active if len(_seat_suits(state, s)) >= 3]
    pigs = set(huazhu)
    points = score_of(5, state.rules["base_score"])
    for pig in huazhu:
        for other in range(4):
            if other == pig or other in pigs:
                continue
            _add_ledger(state, pig, other, points, "tax.huazhu", {"fan_raw": 5})
    non_pigs = [s for s in active if s not in pigs]
    ready: dict[int, int] = {}
    for seat in non_pigs:
        best = _max_wait_points(state, seat)
        if best is not None:
            ready[seat] = best
    for payer in non_pigs:
        if payer in ready:
            continue
        for seat, amount in ready.items():
            _add_ledger(state, payer, seat, amount, "tax.chajiao", {})
    ready_or_won = set(ready) | {s for s in range(4) if state.wins[s] is not None}
    for seat in range(4):
        if seat in ready_or_won:
            continue
        if state.wins[seat] is not None:
            continue
        _refund(state, seat)
    _fold(state)
    dealer_next = _next_dealer(state)
    events.append({"type": "hand_end", "actor": None, "payload": {"reason": reason, "next_dealer": dealer_next, "scores_hand": list(state.scores_hand), "scores_game": list(state.scores_game)}})
    if any(score <= 0 for score in state.scores_game):
        state.phase = "completed"
        state.end_reason = "bust"
        state.turn = None
        state.pending = None
        events.append({"type": "match_end", "actor": None, "payload": {"reason": "bust", "scores": list(state.scores_game)}})
        return
    state.phase = "between_hands"
    state.turn = None
    state.pending = None
    state.end_reason = None


def _refund(state: State, seat: int) -> None:
    for receipt in state.kong_receipts:
        if receipt["seat"] != seat or receipt["refunded"]:
            continue
        kept = max(0, receipt["gross"] - receipt["transferred"])
        if kept <= 0 or kept != receipt["gross"]:
            receipt["refunded"] = True
            continue
        for frm, amount in receipt["payments"]:
            _add_ledger(state, seat, frm, amount, "tax.tuishui", {"receipt_id": receipt["receipt_id"]})
        receipt["refunded"] = True


def _max_wait_points(state: State, seat: int) -> int | None:
    if _has_que(state, seat):
        return None
    if state.dingque[seat] and any(suit_of(m["tiles"][0]) == state.dingque[seat] for m in state.melds[seat]):
        return None
    best: int | None = None
    hand = state.hands[seat]
    melds = _melds(state, seat)
    occupied = set(hand)
    for meld in state.melds[seat]:
        occupied.update(meld["tiles"])
    for key in range(27):
        if _visible_key_count(state, seat, key) >= 4:
            continue
        sample = _unused_id(occupied, key)
        if sample is None:
            continue
        trial = hand + [sample]
        if not is_winning_shape(trial, melds, state.dingque[seat]):
            continue
        fan = evaluate(
            hand,
            melds,
            que=state.dingque[seat],
            base_score=state.rules["base_score"],
            enable_jingoudiao=bool(state.rules.get("enable_jingoudiao")),
            logical_concealed=trial,
        )
        if fan and (best is None or fan.points > best):
            best = fan.points
    return best


def _visible_key_count(state: State, seat: int, key: int) -> int:
    ids: set[int] = set()
    ids.update(state.hands[seat])
    for melds in state.melds:
        for meld in melds:
            ids.update(meld["tiles"])
    for river in state.discards:
        for item in river:
            ids.add(item["tile"])
    for win in state.wins:
        if not win:
            continue
        ids.update(win["hand"])
    if state.pending_ba_kong:
        ids.add(state.pending_ba_kong["tile_id"])
    return sum(1 for tile in ids if key_of(tile) == key)


def _unused_id(occupied: set[int], key: int) -> int | None:
    suit = SUITS[key // 9]
    rank = key % 9 + 1
    for copy in range(4):
        tile = tile_id(suit, rank, copy)
        if tile not in occupied:
            return tile
    return None


def _fold(state: State) -> None:
    _recompute(state)
    if not state.hand_folded:
        state.scores_game = [g + h for g, h in zip(state.scores_game, state.scores_hand)]
        state.hand_folded = True


def _bust(state: State, events: list[dict]) -> bool:
    _recompute(state)
    running = state.scores_game if state.hand_folded else [g + h for g, h in zip(state.scores_game, state.scores_hand)]
    if any(score <= 0 for score in running):
        if state.pending_ba_kong:
            owner = state.pending_ba_kong["seat"]
            state.hands[owner].append(state.pending_ba_kong["tile_id"])
            state.pending_ba_kong = None
        if not state.hand_folded:
            state.scores_game = list(running)
            state.hand_folded = True
        state.phase = "completed"
        state.end_reason = "bust"
        state.turn = None
        state.pending = None
        events.append({"type": "match_end", "actor": None, "payload": {"reason": "bust", "scores": list(state.scores_game)}})
        return True
    return False


def _next_hand(state: State, events: list[dict]) -> None:
    if any(score <= 0 for score in state.scores_game):
        raise RuleError("有人已经输完，这局结束了", "illegal_action", "rule.bust")
    dealer = _next_dealer(state)
    scores = list(state.scores_game)
    rules = state.rules
    seed_hex = state.seed_hex
    hand_index = state.hand_index + 1
    version = state.ruleset_version
    fresh, _ = new_match(rules, bytes.fromhex(seed_hex))
    fresh.hand_index = hand_index
    fresh.scores_game = scores
    fresh.ruleset_version = version
    fresh.seed_hex = seed_hex
    # new_match 已经发了第 0 盘。这里改序号后重发。
    fresh.wall = []
    fresh.hands = [[] for _ in range(4)]
    fresh.melds = [[] for _ in range(4)]
    fresh.discards = [[] for _ in range(4)]
    fresh.dingque = [None] * 4
    fresh.wins = [None] * 4
    fresh.pass_hu = [False] * 4
    fresh.after_kong = [False] * 4
    fresh.last_kong_receipt_id = [None] * 4
    fresh.drawn_this_turn = [None] * 4
    fresh.draws_taken = [0] * 4
    fresh.any_kong_or_pong = False
    fresh.dealer_has_discarded = False
    fresh.must_hu = False
    fresh.pending = None
    fresh.pending_ba_kong = None
    fresh.kong_receipts = []
    fresh.ledger = []
    fresh.scores_hand = [0, 0, 0, 0]
    fresh.hand_folded = False
    fresh.hu_events = []
    fresh.end_reason = None
    fresh.receipt_seq = 0
    state.__dict__.update(fresh.__dict__)
    _deal(state, events, dealer=dealer)


def _next_dealer(state: State) -> int:
    if not state.hu_events:
        return state.dealer
    first = state.hu_events[0]
    if len(first["seats"]) == 1:
        return first["seats"][0]
    return first["provider"]


def _add_ledger(
    state: State,
    frm: int,
    to: int,
    amount: int,
    clause: str,
    detail: dict | None = None,
    fan_raw: int | None = None,
    fan_charged: int | None = None,
) -> None:
    if amount <= 0 or frm == to:
        return
    state.ledger.append(
        {
            "clause_id": clause,
            "from_seat": frm,
            "to_seat": to,
            "amount": amount,
            "fan_raw": fan_raw if fan_raw is not None else (detail or {}).get("fan_raw"),
            "fan_charged": fan_charged if fan_charged is not None else (detail or {}).get("fan_charged"),
            "detail": detail or {},
        }
    )
    _recompute(state)


def _recompute(state: State) -> None:
    scores = [0, 0, 0, 0]
    for entry in state.ledger:
        scores[entry["from_seat"]] -= entry["amount"]
        scores[entry["to_seat"]] += entry["amount"]
    state.scores_hand = scores


def _close_after_kong(state: State, seat: int) -> None:
    state.after_kong[seat] = False


def _has_que(state: State, seat: int) -> bool:
    que = state.dingque[seat]
    return bool(que) and any(suit_of(tile) == que for tile in state.hands[seat])


def _can_zimo(state: State, seat: int) -> bool:
    if _has_que(state, seat):
        return False
    return is_winning_shape(state.hands[seat], _melds(state, seat), state.dingque[seat])


def _can_hu_tile(state: State, seat: int, tile: int, from_discard: bool) -> bool:
    if state.wins[seat] is not None or _has_que(state, seat):
        return False
    if state.dingque[seat] and suit_of(tile) == state.dingque[seat]:
        return False
    if from_discard and state.pass_hu[seat] and not state.must_hu:
        return False
    trial = list(state.hands[seat]) + [tile]
    return is_winning_shape(trial, _melds(state, seat), state.dingque[seat])


def _can_pong(state: State, seat: int, tile: int) -> bool:
    if _has_que(state, seat) or (state.dingque[seat] and suit_of(tile) == state.dingque[seat]):
        return False
    return sum(1 for item in state.hands[seat] if key_of(item) == key_of(tile)) >= 2


def _can_zhi_kong(state: State, seat: int, tile: int) -> bool:
    if not state.wall or _has_que(state, seat):
        return False
    if state.dingque[seat] and suit_of(tile) == state.dingque[seat]:
        return False
    return sum(1 for item in state.hands[seat] if key_of(item) == key_of(tile)) >= 3


def _melds(state: State, seat: int) -> list[Meld]:
    return [Meld(m["kind"], list(m["tiles"]), m.get("from_seat")) for m in state.melds[seat]]


def _seat_suits(state: State, seat: int) -> set[str]:
    found = {suit_of(t) for t in state.hands[seat]}
    for meld in state.melds[seat]:
        found.add(suit_of(meld["tiles"][0]))
    return found


def _groups(hand: list[int]) -> dict[int, list[int]]:
    grouped: dict[int, list[int]] = {}
    for tile in hand:
        grouped.setdefault(key_of(tile), []).append(tile)
    return grouped


def _active_except(state: State, seat: int) -> list[int]:
    return [s for s in range(4) if s != seat and state.wins[s] is None]


def _next_active(state: State, start: int) -> int | None:
    for step in range(4):
        seat = next_seat(start, step)
        if state.wins[seat] is None:
            return seat
    return None


def _valid_exchange(hand: list[int], tiles: list[int]) -> bool:
    if len(tiles) != 3 or len(set(tiles)) != 3:
        return False
    if any(tile not in hand for tile in tiles):
        return False
    return len({suit_of(tile) for tile in tiles}) == 1


def _same_action(action: dict, allowed: list[dict]) -> bool:
    for item in allowed:
        if item["type"] != action.get("type"):
            continue
        if item["type"] == "discard" and int(action.get("tile", -1)) == item["tile"]:
            return True
        if item["type"] == "kong" and action.get("kong_kind") == item["kong_kind"] and key_of(int(action.get("tile", -1))) == key_of(item["tile"]):
            return True
        if item["type"] in ("hu", "pong", "pass", "next_hand", "end_game", "exchange"):
            return True
        if item["type"] == "dingque" and action.get("suit") == item["suit"]:
            return True
    return False


def _assert_state(state: State) -> None:
    ids: list[int] = []
    ids.extend(state.wall)
    for hand in state.hands:
        ids.extend(hand)
    for melds in state.melds:
        for meld in melds:
            ids.extend(meld["tiles"])
    for river in state.discards:
        for item in river:
            ids.append(item["tile"])
    if state.pending_ba_kong:
        ids.append(state.pending_ba_kong["tile_id"])
    if sorted(ids) != list(range(108)):
        raise RuleError(f"牌张不守恒: {len(ids)}", "invariant", "tile_conservation")
    if sum(state.scores_hand) != 0:
        raise RuleError("本盘账本不是零和", "invariant", "zero_sum")
    if sum(state.scores_game) != INITIAL_POINTS * 4:
        raise RuleError("整局分数合计不是 400", "invariant", "zero_sum")
    if state.turn is not None and state.wins[state.turn] is not None:
        raise RuleError("已胡的人不能继续出牌", "invariant")


def collect_ids(state: State) -> list[int]:
    _assert_state(state)
    return []
