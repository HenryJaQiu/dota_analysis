"""Data-driven verdict: losing-side responsibility and winning-side MVP."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from app.config import settings
from app.models.analysis import (
    MatchAnalysis,
    MatchVerdict,
    PlayerAnalysis,
    PlayerVerdict,
    VerdictMetric,
)
from app.models.match import ParseStatus

logger = logging.getLogger(__name__)

PROFILE_LABELS = {
    "balanced": "均衡评估",
    "strict": "严格分锅",
    "gentle": "温和复盘",
}

# Base weights. Profiles apply multipliers below and then normalize.
BASE_WEIGHTS = {
    "core": {
        "gpm": 0.11,
        "xpm": 0.04,
        "last_hits": 0.06,
        "net_worth": 0.06,
        "economy_share": 0.05,
        "hero_damage": 0.12,
        "damage_share": 0.05,
        "tower_damage": 0.04,
        "tower_share": 0.03,
        "kda": 0.11,
        "deaths": 0.05,
        "key_deaths": 0.05,
        "teamfight_deaths": 0.03,
        "participation": 0.03,
        "kill_share": 0.04,
        "vision": 0.01,
        "healing": 0.01,
        "objectives": 0.03,
        "lane_evaluation": 0.05,
        "item_timing": 0.03,
    },
    "support": {
        "gpm": 0.03,
        "xpm": 0.03,
        "last_hits": 0.02,
        "net_worth": 0.02,
        "economy_share": 0.02,
        "hero_damage": 0.07,
        "damage_share": 0.04,
        "tower_damage": 0.01,
        "tower_share": 0.01,
        "kda": 0.09,
        "deaths": 0.07,
        "key_deaths": 0.06,
        "teamfight_deaths": 0.04,
        "participation": 0.09,
        "kill_share": 0.08,
        "vision": 0.15,
        "healing": 0.04,
        "objectives": 0.06,
        "lane_evaluation": 0.05,
        "item_timing": 0.02,
    },
}

# Per-metric multipliers. A value of 1.0 means use the base weight.
PROFILE_MULTIPLIERS = {
    "balanced": {"core": {}, "support": {}},
    "strict": {
        "core": {
            "deaths": 1.6,
            "key_deaths": 1.8,
            "kda": 1.15,
            "gpm": 1.10,
            "last_hits": 1.10,
            "economy_share": 1.20,
            "damage_share": 1.15,
            "hero_damage": 1.10,
            "vision": 0.80,
            "healing": 0.70,
            "objectives": 0.80,
            "participation": 0.90,
        },
        "support": {
            "deaths": 1.50,
            "key_deaths": 1.70,
            "kda": 1.10,
            "vision": 0.80,
            "healing": 0.70,
            "objectives": 0.80,
            "participation": 0.95,
        },
    },
    "gentle": {
        "core": {
            "deaths": 0.50,
            "key_deaths": 0.50,
            "damage_share": 1.05,
            "vision": 1.25,
            "healing": 1.30,
            "objectives": 1.20,
            "participation": 1.15,
            "kill_share": 1.10,
        },
        "support": {
            "deaths": 0.55,
            "key_deaths": 0.55,
            "vision": 1.25,
            "healing": 1.30,
            "objectives": 1.20,
            "participation": 1.15,
            "kill_share": 1.10,
        },
    },
}

METRIC_KEYS = set(BASE_WEIGHTS["core"])

_IGNORE_ALL_ZERO = {
    "economy_share",
    "damage_share",
    "tower_damage",
    "tower_share",
    "vision",
    "healing",
    "objectives",
    "key_deaths",
    "teamfight_deaths",
}

METHODOLOGY = (
    "评分综合 KDA、经济、伤害、参团、死亡、视野与目标控制；"
    "GPM / 补刀 / 英雄伤害会与 OpenDota 同英雄基准混合，对线结合 lane_role、对位英雄克制与 10 分钟经济/经验/补刀差；"
    "死亡会结合团战时间点，装备会参考关键装备购买时间；"
    "经济、伤害、推塔、参团击杀使用队内占比，并按核心 / 辅助位置和所选模式加权。"
    "分数为同队内相对评分，越高代表本场贡献越大；分锅结果仅供复盘参考。"
)


@dataclass
class TeamContext:
    total_damage: float = 0.0
    total_net_worth: float = 0.0
    total_tower_damage: float = 0.0
    total_kills: float = 0.0


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    group: str
    higher_better: bool
    getter: Callable[[PlayerAnalysis, TeamContext], Optional[float]]
    formatter: Callable[[float], str]
    benchmark_getter: Optional[Callable[[PlayerAnalysis], Optional[float]]] = None
    benchmark_blend: float = 0.0


@dataclass
class MetricRow:
    spec: MetricSpec
    value: float
    team_pct: float
    benchmark: Optional[float]
    effective: float
    rank: int
    weight: float


def _fmt_int(value: float) -> str:
    return f"{value:.0f}"


def _fmt_one(value: float) -> str:
    return f"{value:.1f}"


def _fmt_k(value: float) -> str:
    return f"{value / 1000:.1f}k"


def _fmt_pct(value: float) -> str:
    return f"{value:.0f}%"


def _share(value: float, total: float) -> Optional[float]:
    if total is None or total <= 0:
        return None
    return round(max(0.0, float(value)) / total * 100, 1)


def _participation(player: PlayerAnalysis, _ctx: TeamContext) -> Optional[float]:
    value = player.teamfight.participation_rate
    return value * 100 if value is not None else None


def _kill_share(player: PlayerAnalysis, ctx: TeamContext) -> Optional[float]:
    if ctx.total_kills <= 0:
        return None
    return min(
        100.0,
        (player.teamfight.kills + player.teamfight.assists)
        / ctx.total_kills
        * 100,
    )


def _vision_score(player: PlayerAnalysis, _ctx: TeamContext) -> Optional[float]:
    if not player.vision.available:
        return None
    return (
        (player.vision.obs_placed or 0)
        + (player.vision.sen_placed or 0) * 0.6
        + (player.vision.obs_killed or 0) * 1.5
    )


def _objective_score(player: PlayerAnalysis, _ctx: TeamContext) -> Optional[float]:
    if not player.objectives.available:
        return None
    return (
        player.objectives.roshan_kills * 2
        + player.objectives.tormentor_kills
        + player.objectives.wisdom_runes * 0.5
    )


METRICS = [
    MetricSpec(
        "gpm", "GPM", "farm", True,
        lambda p, c: p.economy.gpm, _fmt_int,
        lambda p: p.economy.gpm_benchmark_pct, 0.5,
    ),    MetricSpec(
        "xpm", "XPM", "farm", True,
        lambda p, c: p.economy.xpm, _fmt_int,
    ),
    MetricSpec(
        "last_hits", "补刀", "farm", True,
        lambda p, c: p.economy.last_hits, _fmt_int,
        lambda p: p.economy.lh_benchmark_pct, 0.5,
    ),
    MetricSpec(
        "net_worth", "净身价", "farm", True,
        lambda p, c: p.economy.net_worth, _fmt_k,
    ),
    MetricSpec(
        "economy_share", "经济占比", "farm", True,
        lambda p, c: _share(p.economy.net_worth, c.total_net_worth), _fmt_pct,
    ),
    MetricSpec(
        "hero_damage", "英雄伤害", "damage", True,
        lambda p, c: p.teamfight.hero_damage, _fmt_k,
        lambda p: p.teamfight.hero_damage_benchmark_pct, 0.5,
    ),
    MetricSpec(
        "damage_share", "伤害占比", "damage", True,
        lambda p, c: _share(p.teamfight.hero_damage, c.total_damage), _fmt_pct,
    ),
    MetricSpec(
        "tower_damage", "推塔伤害", "damage", True,
        lambda p, c: p.teamfight.tower_damage, _fmt_k,
    ),
    MetricSpec(
        "tower_share", "推塔占比", "damage", True,
        lambda p, c: _share(p.teamfight.tower_damage, c.total_tower_damage), _fmt_pct,
    ),
    MetricSpec(
        "kda", "KDA", "fight", True,
        lambda p, c: p.teamfight.kda, _fmt_one,
    ),
    MetricSpec(
        "deaths", "死亡", "discipline", False,
        lambda p, c: p.teamfight.deaths, lambda v: f"{v:.0f} 次",
    ),
    MetricSpec(
        "key_deaths", "关键死亡", "discipline", False,
        lambda p, c: p.key_deaths, lambda v: f"{v:.0f} 次",
    ),
    MetricSpec(
        "teamfight_deaths", "团战死亡", "discipline", False,
        lambda p, c: p.teamfight_deaths, lambda v: f"{v:.0f} 次",
    ),
    MetricSpec(
        "participation", "参团率", "team", True,
        _participation, _fmt_pct,
    ),
    MetricSpec(
        "kill_share", "参团击杀占比", "team", True,
        _kill_share, _fmt_pct,
    ),
    MetricSpec(
        "vision", "视野贡献", "support", True,
        _vision_score, _fmt_one,
    ),
    MetricSpec(
        "healing", "治疗量", "support", True,
        lambda p, c: p.teamfight.hero_healing, _fmt_k,
    ),
    MetricSpec(
        "objectives", "目标参与", "objective", True,
        _objective_score, _fmt_one,
    ),
    MetricSpec(
        "lane_evaluation", "对线评价", "lane", True,
        lambda p, c: p.laning.lane_score, _fmt_one,
    ),
    MetricSpec(
        "item_timing", "关键装备时机", "items", True,
        lambda p, c: p.items.key_item_score, _fmt_one,
    ),
]


def resolve_profile(profile: Optional[str]) -> str:
    if profile in PROFILE_LABELS:
        return profile
    default = (settings.verdict_mode or "").strip().lower()
    return default if default in PROFILE_LABELS else "balanced"


def _load_multipliers() -> Dict[str, Dict[str, Dict[str, float]]]:
    result = {
        profile: {
            role: dict(values)
            for role, values in roles.items()
        }
        for profile, roles in PROFILE_MULTIPLIERS.items()
    }

    path = settings.verdict_weights_file
    if not path or not os.path.exists(path):
        return result

    try:
        with open(path, "r", encoding="utf-8") as f:
            custom = json.load(f)
    except Exception as exc:
        logger.warning("Could not read custom verdict weights: %s", exc)
        return result

    if not isinstance(custom, dict):
        return result

    for profile, payload in custom.items():
        if profile not in result or not isinstance(payload, dict):
            continue

        # Flat form applies to both roles.
        flat = {
            key: value
            for key, value in payload.items()
            if key in METRIC_KEYS
        }
        for role in ("core", "support"):
            factors = dict(flat)
            role_payload = payload.get(role)
            if isinstance(role_payload, dict):
                factors.update(
                    {
                        key: value
                        for key, value in role_payload.items()
                        if key in METRIC_KEYS
                    }
                )
            for key, factor in factors.items():
                try:
                    factor = float(factor)
                except (TypeError, ValueError):
                    continue
                if factor > 0:
                    result[profile][role][key] = factor
    return result


def _weight_profiles() -> Dict[str, Dict[str, Dict[str, float]]]:
    multipliers = _load_multipliers()
    profiles: Dict[str, Dict[str, Dict[str, float]]] = {}
    for profile in PROFILE_LABELS:
        profiles[profile] = {}
        for role_key, base in BASE_WEIGHTS.items():
            raw = {
                key: base[key] * multipliers[profile][role_key].get(key, 1.0)
                for key in base
            }
            total = sum(max(0.0, value) for value in raw.values())
            if total <= 0:
                profiles[profile][role_key] = dict(base)
            else:
                profiles[profile][role_key] = {
                    key: value / total for key, value in raw.items()
                }
    return profiles


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


def _effective_pct(spec: MetricSpec, player: PlayerAnalysis, team_pct: float):
    if spec.benchmark_getter is None:
        return team_pct, None
    try:
        benchmark = spec.benchmark_getter(player)
    except Exception:
        benchmark = None
    if benchmark is None:
        return team_pct, None
    blend = max(0.0, min(1.0, spec.benchmark_blend))
    return round((1 - blend) * team_pct + blend * float(benchmark), 1), round(float(benchmark), 1)


def _team_context(team: List[PlayerAnalysis]) -> TeamContext:
    return TeamContext(
        total_damage=sum(max(0.0, p.teamfight.hero_damage or 0) for p in team),
        total_net_worth=sum(max(0.0, p.economy.net_worth or 0) for p in team),
        total_tower_damage=sum(max(0.0, p.teamfight.tower_damage or 0) for p in team),
        total_kills=sum(max(0.0, p.teamfight.kills or 0) for p in team),
    )


def _farm_score(player: PlayerAnalysis) -> float:
    return (player.economy.net_worth or 0) + (player.economy.last_hits or 0) * 100


def _is_support_hero(player: PlayerAnalysis) -> bool:
    roles = {str(role).lower() for role in (player.hero_roles or [])}
    return "support" in roles and "carry" not in roles


def _is_carry_hero(player: PlayerAnalysis) -> bool:
    roles = {str(role).lower() for role in (player.hero_roles or [])}
    return "carry" in roles


def _team_roles(team: List[PlayerAnalysis]) -> Dict[int, str]:
    farm_order = sorted(team, key=_farm_score, reverse=True)

    if not any(player.hero_roles for player in team):
        return {
            player.player_slot: (
                "核心" if index < max(1, len(farm_order) - 2) else "辅助"
            )
            for index, player in enumerate(farm_order)
        }

    roles = {player.player_slot: "核心" for player in team}
    supports = []
    support_slots = set()
    farm_rank = {
        player.player_slot: index
        for index, player in enumerate(farm_order)
    }

    # Prefer support-only heroes that are not top-2 farm; lowest farm first.
    for player in reversed(farm_order):
        if len(supports) >= 2:
            break
        if _is_support_hero(player) and farm_rank[player.player_slot] >= 2:
            supports.append(player)
            support_slots.add(player.player_slot)

    # Fill with the lowest-farm non-carry heroes.
    if len(supports) < 2:
        for player in reversed(farm_order):
            if player.player_slot in support_slots:
                continue
            if _is_carry_hero(player):
                continue
            supports.append(player)
            support_slots.add(player.player_slot)
            if len(supports) >= 2:
                break

    # Last resort: lowest farm players.
    if len(supports) < 2:
        for player in reversed(farm_order):
            if player.player_slot in support_slots:
                continue
            supports.append(player)
            support_slots.add(player.player_slot)
            if len(supports) >= 2:
                break

    for player in supports:
        roles[player.player_slot] = "辅助"
    return roles


def _team_data(
    team: List[PlayerAnalysis],
) -> Tuple[
    Dict[int, str],
    TeamContext,
    Dict[str, Tuple[List[float], Dict[int, float]]],
    Dict[str, Dict[int, float]],
]:
    roles = _team_roles(team)
    context = _team_context(team)
    data: Dict[str, Tuple[List[float], Dict[int, float]]] = {}
    for spec in METRICS:
        values: List[float] = []
        by_slot: Dict[int, float] = {}
        for player in team:
            value = spec.getter(player, context)
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
    return roles, context, data, percentiles


def _player_breakdown(
    player: PlayerAnalysis,
    role: str,
    context: TeamContext,
    data: Dict[str, Tuple[List[float], Dict[int, float]]],
    percentiles: Dict[str, Dict[int, float]],
    weights: Dict[str, float],
    mode: str,
) -> Tuple[float, List[VerdictMetric], List[str]]:
    rows: List[MetricRow] = []
    for spec in METRICS:
        values, by_slot = data[spec.key]
        if not _metric_usable(spec, values):
            continue
        value = by_slot.get(player.player_slot)
        if value is None:
            continue
        weight = weights.get(spec.key, 0.0)
        if weight <= 0:
            continue
        team_pct = percentiles[spec.key].get(player.player_slot, 50.0)
        effective, benchmark = _effective_pct(spec, player, team_pct)
        rank = _rank(values, value, spec.higher_better)
        rows.append(
            MetricRow(
                spec=spec,
                value=value,
                team_pct=team_pct,
                benchmark=benchmark,
                effective=effective,
                rank=rank,
                weight=weight,
            )
        )

    if not rows:
        return 50.0, [], []

    total_weight = sum(row.weight for row in rows)
    metrics: List[VerdictMetric] = []
    score = 0.0
    for row in rows:
        normalized = row.weight / total_weight
        contribution = row.effective * normalized
        score += contribution
        if row.benchmark is not None:
            note = f"队内 {row.team_pct:.1f} / 英雄基准 {row.benchmark:.1f}"
        elif row.spec.key == "key_deaths":
            note = f"团战相关死亡 {player.teamfight_deaths} 次"
        elif row.spec.key == "lane_evaluation" and player.laning.summary:
            note = player.laning.summary
        elif row.spec.key == "item_timing" and player.items.key_items:
            note = " · ".join(
                f"{item.get('item', '')} {item.get('time_str', '')}"
                for item in player.items.key_items[:3]
            )
        else:
            note = None
        metrics.append(
            VerdictMetric(
                key=row.spec.key,
                label=row.spec.label,
                value=row.spec.formatter(row.value),
                score=round(row.effective, 1),
                weight=round(normalized, 4),
                contribution=round(contribution, 1),
                rank=row.rank,
                team_score=row.team_pct,
                benchmark_score=row.benchmark,
                note=note,
            )
        )

    metrics.sort(key=lambda item: (-item.weight, item.label))

    if mode == "blame":
        rows.sort(key=lambda row: (row.effective, -row.weight))
    else:
        rows.sort(key=lambda row: (-row.effective, -row.weight))

    if mode == "blame":
        preferred = [
            row
            for row in rows
            if row.rank >= max(2, len(data[row.spec.key][0]) - 1)
        ]
    else:
        preferred = [row for row in rows if row.rank <= 2]

    chosen: List[MetricRow] = []
    used_groups = set()
    for row in preferred:
        if row.spec.group in used_groups:
            continue
        used_groups.add(row.spec.group)
        chosen.append(row)
        if len(chosen) >= 3:
            break
    if not chosen:
        chosen = rows[:1]

    reasons = [
        f"{row.spec.label} {row.spec.formatter(row.value)}"
        f"（{_rank_text(row.spec, row.rank, len(data[row.spec.key][0]))}）"
        for row in chosen
    ]
    return round(score, 1), metrics, reasons


def _build_team_verdicts(
    team: List[PlayerAnalysis],
    mode: str,
    profile_weights: Dict[str, Dict[str, float]],
) -> List[PlayerVerdict]:
    roles, context, data, percentiles = _team_data(team)
    rows = []
    for player in team:
        role = roles.get(player.player_slot, "辅助")
        role_key = "core" if role == "核心" else "support"
        reason_mode = "blame" if mode == "loser" else "mvp"
        score, metrics, reasons = _player_breakdown(
            player,
            role,
            context,
            data,
            percentiles,
            profile_weights[role_key],
            reason_mode,
        )
        rows.append((player, role, score, reasons, metrics))

    rows.sort(key=lambda row: row[2], reverse=(mode == "winner"))

    verdicts = []
    for rank, (player, role, score, reasons, metrics) in enumerate(rows, start=1):
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
                metrics=metrics,
            )
        )
    return verdicts


def _compute_confidence(match: MatchAnalysis):
    players = match.players
    count = max(1, len(players))

    hero_roles = sum(1 for p in players if p.hero_roles) / count
    benchmark_hits = 0
    for player in players:
        for value in (
            player.economy.gpm_benchmark_pct,
            player.economy.lh_benchmark_pct,
            player.teamfight.hero_damage_benchmark_pct,
        ):
            if value is not None:
                benchmark_hits += 1
    benchmarks = benchmark_hits / (count * 3)
    lane = sum(1 for p in players if p.laning.lane_score is not None) / count
    matchup = sum(1 for p in players if p.laning.matchup_score is not None) / count
    death_timing = sum(1 for p in players if p.death_timing_available) / count
    vision = sum(1 for p in players if p.vision.available) / count
    participation = sum(
        1 for p in players if p.teamfight.participation_rate is not None
    ) / count
    item_timing = sum(1 for p in players if p.items.key_item_score is not None) / count
    timeline = 1.0 if match.timeline else 0.0

    confidence = (
        0.10
        + 0.10 * hero_roles
        + 0.15 * benchmarks
        + 0.20 * lane
        + 0.05 * matchup
        + 0.15 * death_timing
        + 0.10 * vision
        + 0.05 * participation
        + 0.05 * item_timing
        + 0.05 * timeline
    )
    confidence = max(0.0, min(1.0, round(confidence, 2)))

    evidence = []
    if hero_roles < 0.5:
        evidence.append("缺少英雄定位数据，位置判断回退到经济/补刀")
    if benchmarks < 0.5:
        evidence.append("缺少同英雄基准数据，GPM/补刀/伤害部分回退到队内百分位")
    if lane < 0.5:
        evidence.append("缺少对线数据（10 分钟经济/经验/补刀或对线对手）")
    if matchup < 0.5:
        evidence.append("缺少英雄对位胜率，无法修正英雄克制影响")
    if death_timing < 0.5:
        evidence.append("缺少死亡时间/团战窗口，无法计算关键死亡")
    if vision < 0.5:
        evidence.append("缺少视野数据")
    if participation < 0.5:
        evidence.append("缺少团战参与率")
    if item_timing < 0.5:
        evidence.append("缺少关键装备购买时间")
    if timeline <= 0:
        evidence.append("缺少比赛时间轴（肉山/防御塔/买活/关键装备）")

    if confidence >= 0.85:
        label = "高"
    elif confidence >= 0.65:
        label = "中"
    elif confidence >= 0.45:
        label = "低"
    else:
        label = "证据不足"
        if not evidence:
            evidence.append("关键数据覆盖不足，分锅结果可靠性较低")

    return confidence, label, evidence


def build_match_verdict(
    match: MatchAnalysis, profile: Optional[str] = None
) -> Optional[MatchVerdict]:
    if match.parse_status != ParseStatus.PARSED:
        return None

    radiant = [player for player in match.players if player.team == "天辉"]
    dire = [player for player in match.players if player.team == "夜魇"]
    if not radiant or not dire:
        return None

    selected = resolve_profile(profile)
    profile_weights = _weight_profiles()[selected]

    winner_team = "天辉" if match.radiant_win else "夜魇"
    loser_team = "夜魇" if match.radiant_win else "天辉"
    winners = radiant if match.radiant_win else dire
    losers = dire if match.radiant_win else radiant

    winner_rankings = _build_team_verdicts(winners, "winner", profile_weights)
    loser_rankings = _build_team_verdicts(losers, "loser", profile_weights)
    if not winner_rankings or not loser_rankings:
        return None

    confidence, confidence_label, evidence = _compute_confidence(match)

    return MatchVerdict(
        winner_team=winner_team,
        loser_team=loser_team,
        best_player=winner_rankings[0],
        most_responsible=loser_rankings[0],
        winner_rankings=winner_rankings,
        loser_rankings=loser_rankings,
        methodology=METHODOLOGY,
        profile=selected,
        profile_label=PROFILE_LABELS[selected],
        confidence=confidence,
        confidence_label=confidence_label,
        evidence=evidence,
    )
