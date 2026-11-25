from datetime import datetime

from app.models.analysis import (
    EconomyAnalysis,
    ItemAnalysis,
    LaningAnalysis,
    MatchAnalysis,
    ObjectiveAnalysis,
    PlayerAnalysis,
    TeamfightAnalysis,
    VisionAnalysis,
)
from app.models.match import ParseStatus
from app.services.verdict import build_match_verdict


def make_player(
    slot: int,
    team: str,
    hero: str,
    *,
    gpm: int,
    xpm: int,
    last_hits: int,
    net_worth: int,
    damage: int,
    tower_damage: int,
    kills: int,
    deaths: int,
    assists: int,
    participation: float,
    obs: int,
    sen: int,
    obs_killed: int,
    healing: int = 0,
) -> PlayerAnalysis:
    kda = (kills + assists) / max(deaths, 1)
    return PlayerAnalysis(
        player_slot=slot,
        team=team,
        hero_name=hero,
        personaname=f"player{slot}",
        rank_name="万古流芳",
        economy=EconomyAnalysis(
            gpm=gpm,
            xpm=xpm,
            last_hits=last_hits,
            denies=10,
            net_worth=net_worth,
            gold_spent=max(net_worth - 1000, 0),
            gold_timeline=[net_worth // 2, net_worth],
        ),
        teamfight=TeamfightAnalysis(
            participation_rate=participation,
            hero_damage=damage,
            tower_damage=tower_damage,
            hero_healing=healing,
            kills=kills,
            deaths=deaths,
            assists=assists,
            kda=round(kda, 2),
            available=True,
        ),
        items=ItemAnalysis(
            final_items=["假腿", "黑皇杖"],
            aghanims_scepter=False,
            aghanims_shard=False,
            moonshard=False,
            has_timeline=False,
        ),
        vision=VisionAnalysis(
            obs_placed=obs,
            sen_placed=sen,
            obs_killed=obs_killed,
            sen_killed=1,
            available=True,
        ),
        objectives=ObjectiveAnalysis(
            roshan_kills=0,
            tormentor_kills=0,
            wisdom_runes=0,
            available=True,
        ),
        laning=LaningAnalysis(
            lane_name="中路",
            is_roaming=False,
            camps_stacked=0,
            actions_per_min=150,
            available=True,
        ),
        parse_status=ParseStatus.PARSED,
    )


def make_match(parse_status: ParseStatus = ParseStatus.PARSED) -> MatchAnalysis:
    radiant = [
        make_player(
            0, "天辉", "主宰", gpm=680, xpm=760, last_hits=430, net_worth=32000,
            damage=48000, tower_damage=9000, kills=14, deaths=2, assists=8,
            participation=0.72, obs=1, sen=2, obs_killed=1,
        ),
        make_player(
            1, "天辉", "帕克", gpm=610, xpm=700, last_hits=360, net_worth=28000,
            damage=41000, tower_damage=5000, kills=11, deaths=3, assists=12,
            participation=0.75, obs=2, sen=2, obs_killed=2,
        ),
        make_player(
            2, "天辉", "马尔斯", gpm=520, xpm=620, last_hits=280, net_worth=24000,
            damage=30000, tower_damage=4000, kills=6, deaths=5, assists=17,
            participation=0.68, obs=3, sen=3, obs_killed=2,
        ),
        make_player(
            3, "天辉", "水晶室女", gpm=330, xpm=450, last_hits=80, net_worth=14000,
            damage=12000, tower_damage=500, kills=2, deaths=7, assists=20,
            participation=0.55, obs=18, sen=12, obs_killed=5, healing=1200,
        ),
        make_player(
            4, "天辉", "发条技师", gpm=360, xpm=470, last_hits=95, net_worth=15000,
            damage=15000, tower_damage=800, kills=3, deaths=6, assists=19,
            participation=0.58, obs=14, sen=9, obs_killed=4, healing=300,
        ),
    ]
    dire = [
        make_player(
            128, "夜魇", "敌法师", gpm=300, xpm=380, last_hits=180, net_worth=12000,
            damage=6000, tower_damage=1000, kills=0, deaths=14, assists=1,
            participation=0.18, obs=0, sen=0, obs_killed=0,
        ),
        make_player(
            129, "夜魇", "影魔", gpm=560, xpm=650, last_hits=340, net_worth=25000,
            damage=38000, tower_damage=6000, kills=8, deaths=6, assists=5,
            participation=0.48, obs=1, sen=2, obs_killed=1,
        ),
        make_player(
            130, "夜魇", "潮汐猎人", gpm=440, xpm=530, last_hits=210, net_worth=20000,
            damage=16000, tower_damage=2000, kills=2, deaths=8, assists=10,
            participation=0.42, obs=2, sen=3, obs_killed=1,
        ),
        make_player(
            131, "夜魇", "莱恩", gpm=300, xpm=420, last_hits=60, net_worth=12000,
            damage=9000, tower_damage=300, kills=1, deaths=9, assists=12,
            participation=0.38, obs=10, sen=8, obs_killed=2,
        ),
        make_player(
            132, "夜魇", "天涯墨客", gpm=310, xpm=430, last_hits=70, net_worth=12500,
            damage=8000, tower_damage=200, kills=0, deaths=11, assists=9,
            participation=0.30, obs=8, sen=6, obs_killed=1,
        ),
    ]
    return MatchAnalysis(
        match_id=1,
        duration_minutes=40.0,
        radiant_win=True,
        parse_status=parse_status,
        players=radiant + dire,
        analyzed_at=datetime.utcnow(),
    )


def test_verdict_requires_parsed_data():
    assert build_match_verdict(make_match(ParseStatus.NOT_PARSED)) is None


def test_verdict_identifies_winner_mvp_and_loser_blame():
    verdict = build_match_verdict(make_match())
    assert verdict is not None
    assert verdict.winner_team == "天辉"
    assert verdict.loser_team == "夜魇"
    assert verdict.best_player.team == "天辉"
    assert verdict.most_responsible.team == "夜魇"
    assert len(verdict.winner_rankings) == 5
    assert len(verdict.loser_rankings) == 5
    assert [p.rank for p in verdict.loser_rankings] == [1, 2, 3, 4, 5]
    assert verdict.loser_rankings[0].score <= verdict.loser_rankings[-1].score
    assert verdict.winner_rankings[0].score >= verdict.winner_rankings[-1].score
    assert verdict.most_responsible.reasons
    assert verdict.best_player.reasons
    # The intentionally worst-performing Dire core should be blamed first.
    assert verdict.most_responsible.hero_name == "敌法师"


def test_verdict_scores_are_bounded():
    verdict = build_match_verdict(make_match())
    assert verdict is not None
    for player in verdict.winner_rankings + verdict.loser_rankings:
        assert 0.0 <= player.score <= 100.0
        assert player.role in {"核心", "辅助"}
