"""和牌、番型、向听。chengdu-xz-1。"""

from __future__ import annotations

from dataclasses import dataclass, field

from cmahjong.rules.tiles import SUITS, counts_of, rank_of, suit_of

PATTERN_FAN = {
    "pinghu": 1,
    "duidui": 2,
    "qingyise": 3,
    "anqidui": 3,
    "quanyaojiu": 3,
    "qingyaojiu": 4,
    "qingdui": 4,
    "jiangdui": 4,
    "qingqidui": 4,
    "longqidui": 4,
}


class RuleError(Exception):
    def __init__(self, message: str, code: str = "rule_error", clause_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.clause_id = clause_id


def score_of(fan: int, base_score: int, fan_cap: int = 5) -> int:
    if fan < 1:
        raise RuleError("chengdu-xz-1 没有 0 番")
    capped = min(fan, fan_cap)
    return base_score * (1 << (capped - 1))


@dataclass
class Meld:
    kind: str  # pong, zhi_kong, an_kong, ba_kong
    tiles: list[int]
    from_seat: int | None = None

    @property
    def key(self) -> int:
        from cmahjong.rules.tiles import key_of

        return key_of(self.tiles[0])


@dataclass
class FanOut:
    fan_raw: int
    fan_charged: int
    points: int
    patterns: list[str]
    additives: list[str] = field(default_factory=list)
    root_fan: int = 0
    skeleton: str = "standard"


def suits_in(tiles: list[int], melds: list[Meld]) -> set[str]:
    found = {suit_of(t) for t in tiles}
    for meld in melds:
        found.add(suit_of(meld.tiles[0]))
    return found


def contains_suit(tiles: list[int], melds: list[Meld], suit: str | None) -> bool:
    if suit is None:
        return False
    if any(suit_of(t) == suit for t in tiles):
        return True
    return any(suit_of(m.tiles[0]) == suit for m in melds)


def is_winning_shape(tiles: list[int], melds: list[Meld], que: str | None) -> bool:
    if que and contains_suit(tiles, melds, que):
        return False
    if len(suits_in(tiles, melds)) > 2:
        return False
    if not melds and _is_seven_pairs(counts_of(tiles)):
        return True
    return _can_standard(counts_of(tiles), 4 - len(melds))


def _is_seven_pairs(counts: list[int]) -> bool:
    if sum(counts) != 14:
        return False
    pairs = 0
    for count in counts:
        if count == 0:
            continue
        if count not in (2, 4):
            return False
        pairs += count // 2
    return pairs == 7


def _can_standard(counts: list[int], melds_left: int) -> bool:
    return _std(counts[:], 0, melds_left, True)


def _std(counts: list[int], index: int, melds_left: int, need_pair: bool) -> bool:
    while index < 27 and counts[index] == 0:
        index += 1
    if index == 27:
        return melds_left == 0 and not need_pair
    count = counts[index]
    if need_pair and count >= 2:
        counts[index] -= 2
        if _std(counts, index, melds_left, False):
            counts[index] += 2
            return True
        counts[index] += 2
    if melds_left and count >= 3:
        counts[index] -= 3
        if _std(counts, index, melds_left - 1, need_pair):
            counts[index] += 3
            return True
        counts[index] += 3
    rank = index % 9
    if melds_left and rank <= 6 and counts[index + 1] and counts[index + 2]:
        counts[index] -= 1
        counts[index + 1] -= 1
        counts[index + 2] -= 1
        if _std(counts, index, melds_left - 1, need_pair):
            counts[index] += 1
            counts[index + 1] += 1
            counts[index + 2] += 1
            return True
        counts[index] += 1
        counts[index + 1] += 1
        counts[index + 2] += 1
    return False


def root_count(tiles: list[int], melds: list[Meld]) -> int:
    counts = counts_of(tiles)
    for meld in melds:
        counts[meld.key] += len(meld.tiles)
    return sum(1 for count in counts if count == 4)


def _all_ranks(tiles: list[int], melds: list[Meld]) -> list[int]:
    ranks = [rank_of(t) for t in tiles]
    for meld in melds:
        ranks.extend(rank_of(t) for t in meld.tiles)
    return ranks


def _one_suit(tiles: list[int], melds: list[Meld]) -> bool:
    return len(suits_in(tiles, melds)) == 1


@dataclass
class _Part:
    kind: str  # chow, pung, pair
    key: int
    keys: tuple[int, ...]


def _decompositions(counts: list[int], melds_left: int) -> list[list[_Part]]:
    found: list[list[_Part]] = []

    def rec(index: int, left: int, need_pair: bool, acc: list[_Part]) -> None:
        while index < 27 and counts[index] == 0:
            index += 1
        if index == 27:
            if left == 0 and not need_pair:
                found.append(list(acc))
            return
        count = counts[index]
        if need_pair and count >= 2:
            counts[index] -= 2
            acc.append(_Part("pair", index, (index,)))
            rec(index, left, False, acc)
            acc.pop()
            counts[index] += 2
        if left and count >= 3:
            counts[index] -= 3
            acc.append(_Part("pung", index, (index,)))
            rec(index, left - 1, need_pair, acc)
            acc.pop()
            counts[index] += 3
        rank = index % 9
        if left and rank <= 6 and counts[index] and counts[index + 1] and counts[index + 2]:
            counts[index] -= 1
            counts[index + 1] -= 1
            counts[index + 2] -= 1
            acc.append(_Part("chow", index, (index, index + 1, index + 2)))
            rec(index, left - 1, need_pair, acc)
            acc.pop()
            counts[index] += 1
            counts[index + 1] += 1
            counts[index + 2] += 1

    rec(0, melds_left, True, [])
    return found


def _yaojiu_part(part: _Part) -> bool:
    if part.kind == "chow":
        ranks = [k % 9 + 1 for k in part.keys]
        return ranks == [1, 2, 3] or ranks == [7, 8, 9]
    return (part.key % 9 + 1) in (1, 9)


def _pattern_set_standard(parts: list[_Part], tiles: list[int], melds: list[Meld]) -> set[str]:
    meld_kinds = [m.kind for m in melds]
    chows = any(p.kind == "chow" for p in parts)
    if chows or any(k == "chow" for k in meld_kinds):
        duidui = False
    else:
        duidui = True
    qing = _one_suit(tiles, melds)
    yao = all(_yaojiu_part(p) for p in parts) and all(
        rank_of(m.tiles[0]) in (1, 9) for m in melds
    )
    ranks = _all_ranks(tiles, melds)
    jiang = duidui and all(r in (2, 5, 8) for r in ranks)
    matched: set[str] = set()
    if qing and yao:
        matched.add("qingyaojiu")
    if qing and duidui:
        matched.add("qingdui")
    if jiang:
        matched.add("jiangdui")
    if qing:
        matched.add("qingyise")
    if yao:
        matched.add("quanyaojiu")
    if duidui:
        matched.add("duidui")
    if not matched:
        matched.add("pinghu")
    return matched


def _pattern_set_pairs(counts: list[int], tiles: list[int]) -> set[str]:
    quads = sum(1 for c in counts if c == 4)
    qing = _one_suit(tiles, [])
    matched: set[str] = set()
    if qing:
        matched.add("qingqidui")
    if quads:
        matched.add("longqidui")
    if not quads and not qing:
        matched.add("anqidui")
    if not quads and qing:
        pass
    if quads and not qing and "longqidui" not in matched:
        matched.add("longqidui")
    if not matched:
        matched.add("anqidui")
    return matched


def _charge(matched: set[str]) -> tuple[int, list[str], bool]:
    top = max(PATTERN_FAN[name] for name in matched)
    top_set = {name for name in matched if PATTERN_FAN[name] == top}
    root_absorb = top_set == {"longqidui"}
    charged = set(top_set)
    if "longqidui" in charged and len(charged) > 1:
        charged.remove("longqidui")
        root_absorb = False
    return top, sorted(charged), root_absorb


def _jingoudiao(logical_tiles: list[int], melds: list[Meld]) -> bool:
    if len(logical_tiles) != 2:
        return False
    if suit_of(logical_tiles[0]) != suit_of(logical_tiles[1]):
        return False
    if rank_of(logical_tiles[0]) != rank_of(logical_tiles[1]):
        return False
    return all(m.kind in ("pong", "zhi_kong", "an_kong", "ba_kong") for m in melds)


def evaluate(
    concealed: list[int],
    melds: list[Meld],
    *,
    que: str | None = None,
    base_score: int = 1,
    fan_cap: int = 5,
    enable_jingoudiao: bool = False,
    win_kind: str = "zimo",
    after_kong: bool = False,
    wall_after_draw: int | None = None,
    tianhu: bool = False,
    dihu: bool = False,
    logical_concealed: list[int] | None = None,
) -> FanOut | None:
    """concealed 含自摸张。点炮时 concealed 不含和牌张，调用方把和牌张放进 logical。"""
    tiles = list(logical_concealed if logical_concealed is not None else concealed)
    if que and contains_suit(tiles, melds, que):
        return None
    if len(suits_in(tiles, melds)) > 2:
        return None

    candidates: list[tuple[int, int, list[str], int, str]] = []
    counts = counts_of(tiles)
    roots = root_count(tiles, melds)
    jiao = 1 if enable_jingoudiao and _jingoudiao(tiles, melds) else 0

    def shape_fan(pattern_fan: int, absorb: bool, with_jiao: int) -> tuple[int, int]:
        root_fan = max(0, roots - 1) if absorb else roots
        return pattern_fan + root_fan + with_jiao, root_fan

    if not melds and _is_seven_pairs(counts):
        matched = _pattern_set_pairs(counts, tiles)
        pattern_fan, charged, absorb = _charge(matched)
        total, root_fan = shape_fan(pattern_fan, absorb, 0)
        candidates.append((total, pattern_fan, charged, root_fan, "qidui"))
    need = 4 - len(melds)
    if _can_standard(counts, need) and sum(counts) == 3 * need + 2:
        best_local: tuple[int, int, list[str], int] | None = None
        for parts in _decompositions(counts[:], need):
            matched = _pattern_set_standard(parts, tiles, melds)
            pattern_fan, charged, absorb = _charge(matched)
            total, root_fan = shape_fan(pattern_fan, absorb, jiao)
            if best_local is None or total > best_local[0]:
                best_local = (total, pattern_fan, charged, root_fan)
        if best_local is not None:
            candidates.append((best_local[0], best_local[1], best_local[2], best_local[3], "standard"))
    if not candidates:
        return None

    # 比未封顶的形状番。相等时七对优先。过程番不参与选择。
    def sort_key(item: tuple[int, int, list[str], int, str]) -> tuple[int, int]:
        return (item[0], 1 if item[4] == "qidui" else 0)

    total, _pattern_fan, charged, root_fan, skeleton = max(candidates, key=sort_key)
    process = 0
    process_ids: list[str] = []
    for name, bit, amount in (
        ("gangshanghua", win_kind == "zimo" and after_kong, 1),
        ("gangshangpao", win_kind == "dianpao" and after_kong, 1),
        ("qianggang", win_kind == "qianggang", 1),
        ("haidi", win_kind == "zimo" and wall_after_draw == 0, 1),
        ("tianhu", tianhu, 4),
        ("dihu", dihu, 4),
    ):
        if bit:
            process += amount
            process_ids.append(name)
    fan_raw = total + process
    additives = (["gen"] * root_fan) + (["jingoudiao"] if skeleton == "standard" and jiao else []) + process_ids
    return FanOut(
        fan_raw=fan_raw,
        fan_charged=min(fan_raw, fan_cap),
        points=score_of(fan_raw, base_score, fan_cap),
        patterns=charged,
        additives=additives,
        root_fan=root_fan,
        skeleton=skeleton,
    )


def waits(
    concealed: list[int],
    melds: list[Meld],
    que: str | None,
) -> list[int]:
    """返回能胡的 key（0..26）。不含和牌张的暗手。"""
    if que and any(suit_of(t) == que for t in concealed):
        return []
    if any(suit_of(m.tiles[0]) == que for m in melds if que):
        return []
    found: list[int] = []
    base = counts_of(concealed)
    for key in range(27):
        if base[key] >= 4:
            continue
        trial = concealed + [_key_to_sample(key)]
        if is_winning_shape(trial, melds, que):
            found.append(key)
    return found


def _key_to_sample(key: int) -> int:
    suit = SUITS[key // 9]
    rank = key % 9 + 1
    from cmahjong.rules.tiles import tile_id

    return tile_id(suit, rank, 0)


def shanten(concealed: list[int], open_melds: int) -> int:
    """向听。和牌为 -1，听牌为 0。更高向听用贪心，够人机选牌，避免全搜索。"""
    counts = counts_of(concealed)
    need = 4 - open_melds
    win_tiles = 3 * need + 2
    if len(concealed) == win_tiles and _wins_counts(counts, need, open_melds):
        return -1
    if len(concealed) == win_tiles - 1:
        for key in range(27):
            if counts[key] >= 4:
                continue
            counts[key] += 1
            won = _wins_counts(counts, need, open_melds)
            counts[key] -= 1
            if won:
                return 0
    standard = _greedy_shanten(counts[:], need)
    if open_melds == 0 and len(concealed) >= 13:
        return min(standard, _shanten_pairs(counts))
    return standard


def _wins_counts(counts: list[int], need: int, open_melds: int) -> bool:
    if _can_standard(counts, need):
        return True
    return open_melds == 0 and _is_seven_pairs(counts)


def _greedy_shanten(counts: list[int], need: int) -> int:
    sets = 0
    for index in range(27):
        while counts[index] >= 3 and sets < need:
            counts[index] -= 3
            sets += 1
    for index in range(27):
        rank = index % 9
        while sets < need and rank <= 6 and counts[index] and counts[index + 1] and counts[index + 2]:
            counts[index] -= 1
            counts[index + 1] -= 1
            counts[index + 2] -= 1
            sets += 1
    pair = False
    for index in range(27):
        if counts[index] >= 2:
            counts[index] -= 2
            pair = True
            break
    taatsu = 0
    for index in range(27):
        if counts[index] >= 2 and sets + taatsu < need:
            counts[index] -= 2
            taatsu += 1
    for index in range(27):
        rank = index % 9
        if sets + taatsu >= need:
            break
        if rank <= 7 and counts[index] and counts[index + 1]:
            counts[index] -= 1
            counts[index + 1] -= 1
            taatsu += 1
        if sets + taatsu < need and rank <= 6 and counts[index] and counts[index + 2]:
            counts[index] -= 1
            counts[index + 2] -= 1
            taatsu += 1
    if sets > need:
        sets = need
    if sets + taatsu > need:
        taatsu = need - sets
    return (need - sets) * 2 - taatsu - (1 if pair else 0)


def _shanten_pairs(counts: list[int]) -> int:
    pairs = sum(1 for c in counts if c >= 2)
    # 四张算两对
    pairs += sum(1 for c in counts if c >= 4)
    kinds = sum(1 for c in counts if c > 0)
    # 七对向听：6 - 对子数，多余的种类会占位
    sh = 6 - pairs
    if kinds < 7:
        sh += 7 - kinds
    return sh


def _shanten_std(counts: list[int], need: int) -> int:
    best = 8
    work = counts[:]

    def finish(sets: int, taatsu: int, pair: bool) -> None:
        nonlocal best
        if sets > need:
            sets = need
        if sets + taatsu > need:
            taatsu = max(0, need - sets)
        value = (need - sets) * 2 - taatsu - (1 if pair else 0)
        if value < best:
            best = value

    def dfs(index: int, sets: int, taatsu: int, pair: bool) -> None:
        if best <= -1:
            return
        while index < 27 and work[index] == 0:
            index += 1
        if index == 27 or sets + taatsu > need:
            finish(sets, taatsu, pair)
            return
        # 刻子
        if work[index] >= 3 and sets < need:
            work[index] -= 3
            dfs(index, sets + 1, taatsu, pair)
            work[index] += 3
        # 将
        if work[index] >= 2 and not pair:
            work[index] -= 2
            dfs(index, sets, taatsu, True)
            work[index] += 2
        # 对子搭子
        if work[index] >= 2 and pair and sets + taatsu < need:
            work[index] -= 2
            dfs(index, sets, taatsu + 1, pair)
            work[index] += 2
        rank = index % 9
        if sets < need and rank <= 6 and work[index] and work[index + 1] and work[index + 2]:
            work[index] -= 1
            work[index + 1] -= 1
            work[index + 2] -= 1
            dfs(index, sets + 1, taatsu, pair)
            work[index] += 1
            work[index + 1] += 1
            work[index + 2] += 1
        if sets + taatsu < need and rank <= 7 and work[index] and work[index + 1]:
            work[index] -= 1
            work[index + 1] -= 1
            dfs(index, sets, taatsu + 1, pair)
            work[index] += 1
            work[index + 1] += 1
        if sets + taatsu < need and rank <= 6 and work[index] and work[index + 2]:
            work[index] -= 1
            work[index + 2] -= 1
            dfs(index, sets, taatsu + 1, pair)
            work[index] += 1
            work[index + 2] += 1
        # 当前点数剩下的全部当作废张，一次跳到下一点数。
        saved = work[index]
        work[index] = 0
        dfs(index + 1, sets, taatsu, pair)
        work[index] = saved

    dfs(0, 0, 0, False)
    return best
