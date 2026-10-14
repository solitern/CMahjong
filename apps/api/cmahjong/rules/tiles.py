"""108 张牌。id = suit * 36 + (rank - 1) * 4 + copy。"""

from __future__ import annotations

SUITS = ("wan", "tiao", "tong")
SUIT_CHAR = {"wan": "万", "tiao": "条", "tong": "筒"}
CHAR_SUIT = {"万": "wan", "条": "tiao", "筒": "tong"}

INITIAL_POINTS = 100


def suit_index(tile: int) -> int:
    return tile // 36


def suit_of(tile: int) -> str:
    return SUITS[tile // 36]


def rank_of(tile: int) -> int:
    return (tile % 36) // 4 + 1


def copy_of(tile: int) -> int:
    return tile % 4


def key_of(tile: int) -> int:
    """0..26，同一门同一点数共享。"""
    return suit_index(tile) * 9 + rank_of(tile) - 1


def tile_id(suit: str, rank: int, copy: int = 0) -> int:
    return SUITS.index(suit) * 36 + (rank - 1) * 4 + copy


def tile_label(tile: int) -> str:
    return f"{rank_of(tile)}{SUIT_CHAR[suit_of(tile)]}"


def counts_of(tiles: list[int]) -> list[int]:
    counts = [0] * 27
    for tile in tiles:
        counts[key_of(tile)] += 1
    return counts


def parse_hand(text: str) -> list[int]:
    """按书写顺序分配副本。例：'11223344556677万' 或 '123万456条99筒'。"""
    used = [0] * 27
    tiles: list[int] = []
    ranks: list[int] = []
    for ch in text.replace(" ", ""):
        if ch in CHAR_SUIT:
            suit = CHAR_SUIT[ch]
            for rank in ranks:
                key = SUITS.index(suit) * 9 + rank - 1
                copy = used[key]
                if copy > 3:
                    raise ValueError(f"超过 4 张: {rank}{ch}")
                used[key] += 1
                tiles.append(tile_id(suit, rank, copy))
            ranks = []
        elif ch.isdigit() and ch != "0":
            ranks.append(int(ch))
        else:
            raise ValueError(f"无法解析: {ch}")
    if ranks:
        raise ValueError("花色没有写完")
    return tiles


def next_seat(seat: int, step: int = 1) -> int:
    return (seat + step) % 4
