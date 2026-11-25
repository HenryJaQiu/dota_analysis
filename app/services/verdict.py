"""Data-driven post-parse verdict: losing-side responsibility and winning-side MVP."""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from app.models.analysis import (
    MatchAnalysis,
    MatchVerdict,
    PlayerAnalysis,
    PlayerVerdict,
)
from app.models.match import ParseStatus


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    group: str
    higher_better: bool
    core_weight: float
    support_weight: float
    getter: Callable[[PlayerAnalysis], Optional[float]]
    formatter: Callable[[float], str]


def _fmt_int(value: float) -> str:
    return f"{value:.0f}"


def _fmt_one(value: float) -> str:
    return f"{value:.1f}"


def _fmt_k(value: float) -> str:
    return f"{value / 1000:.1f}k"


def _fmt_pct(value: float) -> str:
    return f"{value:.0f}%"


def _participation(player: PlayerAnalysis) -> Optional[float]:
    value = player.teamfight.participation_rate
    return value * 100 if value is not None else None


def _vision_score(player: PlayerAnalysis) -> Optional[float]:
    if not player.vision.available:
        return None
    return (
        (player.vision.obs_placed or 0)
        + (player.vision.sen_placed or 0) * 0.6
        + (player.vision.obs_killed or 0) * 1.5
    )


def _objective_score(player: PlayerAnalysis) -> Optional[float]:
    if not player.objectives.available:
        return None
    return (
        player.objectives.roshan_kills * 2
        + player.objectives.tormentor_kills
        + player.objectives.wisdom_runes * 0.5
    )


METRICS = [
    MetricSpec(
        "gpm", "GPM", "farm", True, 0.15, 0.04,
        lambda p: p.economy.gpm, _fmt_int,
    ),
    MetricSpec(
        "xpm", "XPM", "farm", True, 0.08, 0.04,
        lambda p: p.economy.xpm, _fmt_int,
    ),
    MetricSpec(
        "last_hits", "补刀", "farm", True, 0.09, 0.02,
        lambda p: p.economy.last_hits, _fmt_int,
    ),
    MetricSpec(
        "net_worth", "净身价", "farm", True, 0.10, 0.03,
        lambda p: p.economy.net_worth, _fmt_k,
    ),
    MetricSpec(
        "hero_damage", "英雄伤害", "damage", True, 0.18, 0.10,
        lambda p: p.teamfight.hero_damage, _fmt_k,
    ),
    MetricSpec(
        "tower_damage", "推塔伤害", "damage", True, 0.07, 0.02,
        lambda p: p.teamfight.tower_damage, _fmt_k,
    ),
    MetricSpec(
        "kda", "KDA", "fight", True, 0.14, 0.12,
        lambda p: p.teamfight.kda, _fmt_one,
    ),
    MetricSpec(
        "deaths", "死亡", "discipline", False, 0.05, 0.09,
        lambda p: p.teamfight.deaths, lambda v: f"{v:.0f} 次",
    ),
    MetricSpec(
        "participation", "参团率", "team", True, 0.07, 0.16,
        _participation, _fmt_pct,
    ),
    MetricSpec(
        "vision", "视野贡献", "support", True, 0.02, 0.22,
        _vision_score, _fmt_one,
    ),
    MetricSpec(
        "healing", "治疗量", "support", True, 0.02, 0.08,
        lambda p: p.teamfight.hero_healing, _fmt_k,
    ),
    MetricSpec(
        "objectives", "目标参与", "objective", True, 0.03, 0.08,
        _objective_score, _fmt_one,
    ),
]

# Metrics where an all-zero team value carries no useful signal.
_IGNORE_ALL_ZERO = {"tower_damage", "vision", "healing", "objectives"}

METHODOLOGY = (
    "评分综合 KDA、GPM/XPM、补刀、净身价、英雄与推塔伤害、参团率、死亡次数、"
    "视野和目标控制，并按核心 / 辅助位置加权；分数为同队内相对评分，"
    "越高代表本场贡献越大。分锅结果由数据模型生成，仅供复盘参考。"
)


def _percentile(values: List[float], value: float, higher_better: bool) -> float:
    if not values:
        return 50.0
    if len(values) == 1:
        return 50.0
    if higher_better:
        less = sum(1 for item in values if item < value)
        equal = sum(1 for item in values if item == value)
        rank = less + (equal - 1) / 2
    else:
        greater = sum(1 for item in values if item > value)
        equal = sum(1 for item in values if item == value)
        rank = greater + (equal - 1) / 2
    return round(rank / (len(values) - 1) * 100, 1)


def _rank(values: List[float], value: float, higher_better: bool) -> int:
    ordered = sorted(values, reverse=higher_better)
    for index, item in enumerate(ordered, start=1):
        if item == value:
            return index
    return len(values)


def _rank_text(spec: MetricSpec, rank: int, total: int) -> str:
    if spec.higher_better:
        if rank == 1:
            return "队内最高"
        if rank == total:
            return "队内最低"
    else:
        if rank == 1:
            return "队内最低"
        if rank == total:
            return "队内最高"
    return f"队内第 {rank}"


def _metric_usable(spec: MetricSpec, values: List[float]) -> bool:
    if not values:
        return False
    if spec.key in _IGNORE_ALL_ZERO and max(values) <= 0:
        return False
    return True


def _team_roles(team: List[PlayerAnalysis]) -> Dict[int, str]:
    # Net worth alone can misclassify an underfarmed carry as a support.
    # Last hits are a useful secondary signal for farm priority.
    ordered = sorted(
        team,
        key=lambda p: (
            (p.economy.net_worth or 0) + (p.economy.last_hits or 0) * 100,
            p.economy.gpm or 0,
        ),
        reverse=True,
    )
    return {
        player.player_slot: ("核心" if index < 3 else "辅助")
        for index, player in enumerate(ordered)
    }


def _team_data(
    team: List[PlayerAnalysis],
) -> Tuple[
    Dict[int, str],
    Dict[str, Tuple[List[float], Dict[int, float]]],
    Dict[str, Dict[int, float]],
]:
    roles = _team_roles(team)
    data: Dict[str, Tuple[List[float], Dict[int, float]]] = {}
    for spec in METRICS:
        values: List[float] = []
        by_slot: Dict[int, float] = {}
        for player in team:
            value = spec.getter(player)
            if value is None:
                continue
            value = float(value)
            values.append(value)
            by_slot[player.player_slot] = value
        data[spec.key] = (values, by_slot)

    percentiles: Dict[str, Dict[int, float]] = {}
    for spec in METRICS:
        values, by_slot = data[spec.key]
        percentiles[spec.key] = {
            slot: _percentile(values, value, spec.higher_better)
            for slot, value in by_slot.items()
        }
    return roles, data, percentiles


def _player_score(
    player: PlayerAnalysis,
    role: str,
    data: Dict[str, Tuple[List[float], Dict[int, float]]],
    percentiles: Dict[str, Dict[int, float]],
) -> float:
    total_weight = 0.0
    weighted = 0.0
    for spec in METRICS:
        values, by_slot = data[spec.key]
        if not _metric_usable(spec, values):
            continue
        if player.player_slot not in by_slot:
            continue
        weight = spec.core_weight if role == "核心" else spec.support_weight
        if weight <= 0:
            continue
        pct = percentiles[spec.key].get(player.player_slot)
        if pct is None:
            continue
        weighted += pct * weight
        total_weight += weight
    return round(weighted / total_weight, 1) if total_weight else 50.0


def _player_reasons(
    player: PlayerAnalysis,
    role: str,
    data: Dict[str, Tuple[List[float], Dict[int, float]]],
    percentiles: Dict[str, Dict[int, float]],
    mode: str,
) -> List[str]:
    rows = []
    for spec in METRICS:
        values, by_slot = data[spec.key]
        if not _metric_usable(spec, values):
            continue
        value = by_slot.get(player.player_slot)
        if value is None:
            continue
        weight = spec.core_weight if role == "核心" else spec.support_weight
        if weight < 0.02:
            continue
        pct = percentiles[spec.key].get(player.player_slot, 50.0)
        rank = _rank(values, value, spec.higher_better)
        rows.append((spec, value, pct, rank, weight))

    if not rows:
        return []

    if mode == "blame":
        rows.sort(key=lambda row: (row[2], -row[4]))
    else:
        rows.sort(key=lambda row: (-row[2], -row[4]))

    if mode == "blame":
        preferred = [
            row
            for row in rows
            if row[3] >= max(2, len(data[row[0].key][0]) - 1)
        ]
    else:
        preferred = [row for row in rows if row[3] <= 2]

    chosen = []
    used_groups = set()
    for row in preferred:
        spec = row[0]
        if spec.group in used_groups:
            continue
        used_groups.add(spec.group)
        chosen.append(row)
        if len(chosen) >= 3:
            break

    if not chosen:
        chosen = rows[:1]

    return [
        f"{spec.label} {spec.formatter(value)}（{_rank_text(spec, rank, len(data[spec.key][0]))}）"
        for spec, value, _pct, rank, _weight in chosen
    ]


def _build_team_verdicts(
    team: List[PlayerAnalysis], mode: str
) -> List[PlayerVerdict]:
    roles, data, percentiles = _team_data(team)
    rows = []
    for player in team:
        role = roles.get(player.player_slot, "辅助")
        score = _player_score(player, role, data, percentiles)
        reason_mode = "blame" if mode == "loser" else "mvp"
        reasons = _player_reasons(player, role, data, percentiles, reason_mode)
        rows.append((player, role, score, reasons))

    rows.sort(key=lambda row: row[2], reverse=(mode == "winner"))

    verdicts = []
    for rank, (player, role, score, reasons) in enumerate(rows, start=1):
        verdicts.append(
            PlayerVerdict(
                player_slot=player.player_slot,
                personaname=player.personaname,
                hero_name=player.hero_name,
                team=player.team,
                role=role,
                score=score,
                rank=rank,
                reasons=reasons,
            )
        )
    return verdicts


def build_match_verdict(match: MatchAnalysis) -> Optional[MatchVerdict]:
    if match.parse_status != ParseStatus.PARSED:
        return None

    radiant = [player for player in match.players if player.team == "天辉"]
    dire = [player for player in match.players if player.team == "夜魇"]
    if not radiant or not dire:
        return None

    winner_team = "天辉" if match.radiant_win else "夜魇"
    loser_team = "夜魇" if match.radiant_win else "天辉"
    winners = radiant if match.radiant_win else dire
    losers = dire if match.radiant_win else radiant

    winner_rankings = _build_team_verdicts(winners, "winner")
    loser_rankings = _build_team_verdicts(losers, "loser")
    if not winner_rankings or not loser_rankings:
        return None

    return MatchVerdict(
        winner_team=winner_team,
        loser_team=loser_team,
        best_player=winner_rankings[0],
        most_responsible=loser_rankings[0],
        winner_rankings=winner_rankings,
        loser_rankings=loser_rankings,
        methodology=METHODOLOGY,
    )
