"""启发式人机。能胡则胡，出牌让向听下降。不是强 AI。"""

from __future__ import annotations

from cmahjong.rules.tiles import key_of, rank_of, suit_of
from cmahjong.rules.win import Meld, shanten

VERSION = "heuristic-v1"


def decide(view: dict) -> dict:
    actions = view["legal_actions"]
    if any(item["type"] == "hu" for item in actions):
        return {"type": "hu"}
    if view["phase"] == "exchanging":
        return {"type": "exchange", "tiles": _choose_three(view["hand"])}
    if view["phase"] == "dingque":
        return {"type": "dingque", "suit": _worst_suit(view["hand"])}
    if actions and all(item["type"] == "pass" for item in actions):
        return {"type": "pass"}
    if view["phase"] == "turn_discard":
        return _discard_or_kong(view, actions)
    if view["phase"] in ("await_claims", "await_rob"):
        return _claim(view, actions)
    return actions[0]


def _counts(hand: list[int]) -> dict[str, list[int]]:
    by = {suit: [0] * 9 for suit in ("wan", "tiao", "tong")}
    for tile in hand:
        by[suit_of(tile)][rank_of(tile) - 1] += 1
    return by


def _usefulness(ranks: list[int]) -> int:
    score = 0
    for count in ranks:
        if count >= 3:
            score += 4
        elif count == 2:
            score += 3
    for index, count in enumerate(ranks):
        if count and index < 8 and ranks[index + 1]:
            score += 2
    return score


def _worst_suit(hand: list[int]) -> str:
    by = _counts(hand)
    return min(
        ("wan", "tiao", "tong"),
        key=lambda suit: (sum(by[suit]), _usefulness(by[suit]), suit),
    )


def _choose_three(hand: list[int]) -> list[int]:
    by = _counts(hand)
    suit = min(
        (name for name in ("wan", "tiao", "tong") if sum(by[name]) >= 3),
        key=lambda name: (_usefulness(by[name]) / sum(by[name]), sum(by[name]), name),
    )
    tiles = [tile for tile in hand if suit_of(tile) == suit]
    ranks = {}
    for tile in tiles:
        ranks.setdefault(rank_of(tile), []).append(tile)

    def priority(tile: int) -> tuple:
        group = ranks[rank_of(tile)]
        edge = 0 if rank_of(tile) in (1, 9) else 1
        return (len(group), edge, tile)

    chosen = sorted(tiles, key=priority)[:3]
    return chosen


def _melds(view: dict, seat: int) -> list[Meld]:
    return [Meld(item["kind"], list(item["tiles"]), item.get("from_seat")) for item in view["melds"][str(seat)]]


def _shanten_of(hand: list[int], melds: list[Meld]) -> int:
    return shanten(hand, len(melds))


def _discard_or_kong(view: dict, actions: list[dict]) -> dict:
    que = view["dingque"].get(str(view["self_seat"]))
    que_tiles = [tile for tile in view["hand"] if suit_of(tile) == que] if que else []
    discards = [item for item in actions if item["type"] == "discard"]
    if que_tiles:
        que_discards = [item for item in discards if item["tile"] in que_tiles]
        if que_discards:
            return min(que_discards, key=lambda item: ( _rank_count(view["hand"], item["tile"]), item["tile"]))
    kongs = [item for item in actions if item["type"] == "kong"]
    wall = view["wall_remaining"]
    if wall > 4:
        melds = _melds(view, view["self_seat"])
        current = _shanten_of(view["hand"], melds)
        drawn = view.get("self_drawn_tile")
        for kong in kongs:
            if kong["kong_kind"] == "ba" and kong["tile"] != drawn:
                continue
            if kong["kong_kind"] == "ba" and wall <= 15:
                continue
            if kong["kong_kind"] == "an" and current <= _shanten_of(_without_key(view["hand"], kong["tile"]), melds):
                return kong
            if kong["kong_kind"] == "ba" and wall > 15 and current <= _shanten_of(_without_one(view["hand"], kong["tile"]), melds):
                return kong
    best = None
    melds = _melds(view, view["self_seat"])
    for item in discards:
        hand = _without_one(view["hand"], item["tile"])
        value = (
            _shanten_of(hand, melds),
            _danger(view, item["tile"]) if wall <= 20 else 0,
            item["tile"],
        )
        if best is None or value < best[0]:
            best = (value, item)
    return best[1] if best else discards[0]


def _claim(view: dict, actions: list[dict]) -> dict:
    wall = view["wall_remaining"]
    melds = _melds(view, view["self_seat"])
    current = _shanten_of(view["hand"], melds)
    kong = next((item for item in actions if item["type"] == "kong"), None)
    if kong and wall > 4:
        after = _shanten_of(_without_key_n(view["hand"], kong["tile"], 3), melds + [Meld("zhi_kong", [kong["tile"]] * 4)])
        if after < current or (after == current and current <= 1):
            return kong
    pong = next((item for item in actions if item["type"] == "pong"), None)
    if pong:
        tile = view["discards"][str(_source_guess(view))][-1]["tile"] if False else _claim_tile(view)
        if tile is not None:
            after_hand = _without_key_n(view["hand"], tile, 2)
            after = _shanten_of(after_hand, melds + [Meld("pong", [tile] * 3)])
            if after < current:
                return pong
    return {"type": "pass"}


def _claim_tile(view: dict) -> int | None:
    # 最近一张没有被胡走的弃牌不一定是这张。窗口里的牌在各家牌河末尾、claimed_by 还空。
    # 视图没有单独给 tile。用 pending 不可见。从合法杠或从牌河最后一张推断。
    for action in view["legal_actions"]:
        if action["type"] == "kong" and "tile" in action:
            return action["tile"]
    latest = None
    for river in view["discards"].values():
        if river:
            latest = river[-1]["tile"]
    return latest


def _source_guess(view: dict) -> int:
    return 0


def _without_one(hand: list[int], tile: int) -> list[int]:
    copy = list(hand)
    copy.remove(tile)
    return copy


def _without_key(hand: list[int], tile: int) -> list[int]:
    target = key_of(tile)
    return [item for item in hand if key_of(item) != target]


def _without_key_n(hand: list[int], tile: int, count: int) -> list[int]:
    target = key_of(tile)
    left = count
    kept = []
    for item in hand:
        if key_of(item) == target and left:
            left -= 1
            continue
        kept.append(item)
    return kept


def _rank_count(hand: list[int], tile: int) -> int:
    target = key_of(tile)
    return sum(1 for item in hand if key_of(item) == target)


def _danger(view: dict, tile: int) -> int:
    target = key_of(tile)
    seen = 0
    for river in view["discards"].values():
        seen += sum(1 for item in river if key_of(item["tile"]) == target)
    for melds in view["melds"].values():
        for meld in melds:
            seen += sum(1 for item in meld["tiles"] if key_of(item) == target)
    score = 40
    if seen == 0:
        score += 25
    if seen >= 3:
        score -= 20
    if rank_of(tile) in (1, 9):
        score -= 10
    return score
