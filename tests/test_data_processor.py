from app.models.match import ParseStatus, RawMatch, RawPlayer
from app.services.data_processor import DataProcessor
from app.services.item_timings import timing_percentile
from app.services.lane_utils import build_lane_pairs


def timeline_values(value: int):
    return [value] * 20


def make_raw_player(slot: int, hero_id: int, *, lane: int, gold: int, xp: int, lh: int):
    return RawPlayer(
        player_slot=slot,
        hero_id=hero_id,
        personaname=f"p{slot}",
        lane=lane,
        lane_role=1,
        gold_t=timeline_values(gold),
        xp_t=timeline_values(xp),
        lh_t=timeline_values(lh),
        deaths=3,
        deaths_log=[{"time": 95}, {"time": 105}],
        buyback_log=[{"time": 500}],
        purchase_log=[{"time": 720, "key": "blink"}],
        gold_per_min=500,
        xp_per_min=600,
        last_hits=lh,
        denies=10,
        net_worth=gold,
        gold_spent=gold - 1000,
        kills=5,
        assists=5,
        hero_damage=20000,
        tower_damage=1000,
        hero_healing=0,
    )


def test_lane_items_death_timing_and_timeline():
    raw = RawMatch(
        match_id=42,
        radiant_win=True,
        duration=2400,
        teamfights=[{"start": 100, "end": 120}],
        objectives=[
            {"time": 300, "type": "CHAT_MESSAGE_ROSHAN_KILL", "team": 2},
            {"time": 400, "type": "CHAT_MESSAGE_MINIBOSS_KILL", "team": 2},
            {
                "time": 500,
                "type": "building_kill",
                "key": "npc_dota_badguys_tower1_mid",
                "player_slot": 0,
            },
        ],
        players=[
            make_raw_player(0, 1, lane=1, gold=8000, xp=7000, lh=80),
            make_raw_player(128, 2, lane=1, gold=6000, xp=5500, lh=60),
        ],
    )
    processor = DataProcessor(
        {1: "主宰", 2: "莱恩"},
        {},
        {1: ["Carry", "Escape"], 2: ["Support", "Disabler"]},
        {1: {2: 60.0}},
    )
    analysis = processor.process_match(raw, ParseStatus.PARSED)

    radiant = analysis.players[0]
    assert len(radiant.laning.opponents) == 1
    assert radiant.laning.gold_diff_10 == 2000
    assert radiant.laning.matchup_score == 60.0
    assert radiant.laning.lane_score is not None
    assert radiant.laning.lane_score > 50
    assert radiant.objectives.roshan_kills == 1
    assert radiant.objectives.tormentor_kills == 1
    assert radiant.key_deaths == 2
    assert radiant.death_timing_available is True
    assert radiant.buyback_count == 1
    assert radiant.items.key_items
    assert radiant.items.key_item_score == 100.0

    event_types = {event.type for event in analysis.timeline}
    assert {"roshan", "tormentor", "tower", "buyback", "item"}.issubset(event_types)

    assert (1, 2, 1) in build_lane_pairs(raw.players)
    assert timing_percentile(
        [{"time": 600, "games": 4}, {"time": 900, "games": 6}],
        700,
    ) == 40.0
