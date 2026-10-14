from cmahjong.rules.tiles import parse_hand
from cmahjong.rules.win import evaluate, score_of, shanten


def test_score_table():
    assert [score_of(n, 1) for n in range(1, 7)] == [1, 2, 4, 8, 16, 16]


def test_qingyise_pinghu():
    tiles = parse_hand("12345678934511万")
    fan = evaluate(tiles, [])
    assert fan is not None
    assert fan.patterns == ["qingyise"]
    assert fan.fan_raw == 3
    assert fan.points == 4


def test_qidui_beats_standard():
    tiles = parse_hand("11223344556677万")
    fan = evaluate(tiles, [])
    assert fan is not None
    assert fan.skeleton == "qidui"
    assert "qingqidui" in fan.patterns
    assert fan.fan_raw == 4
    assert fan.points == 8


def test_both_capped_still_prefers_qidui():
    tiles = parse_hand("11112222333344万")
    fan = evaluate(tiles, [])
    assert fan is not None
    assert fan.skeleton == "qidui"
    assert fan.fan_raw == 7
    assert fan.fan_charged == 5
    assert fan.points == 16
    assert fan.root_fan == 3


def test_longqidui_absorbs_first_root():
    tiles = parse_hand("1111223344万5566条")
    fan = evaluate(tiles, [])
    assert fan is not None
    assert fan.patterns == ["longqidui"]
    assert fan.root_fan == 0
    assert fan.fan_raw == 4
    assert fan.points == 8


def test_shanten_complete_and_tenpai():
    won = parse_hand("12345678912399万")
    assert shanten(won, 0) == -1
    tenpai = parse_hand("1234567891239万")
    assert shanten(tenpai, 0) == 0
