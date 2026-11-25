from datetime import datetime
from typing import Dict, List, Optional

from app.models.match import RawMatch, RawPlayer, ParseStatus
from app.models.analysis import (
    EconomyAnalysis,
    TeamfightAnalysis,
    ItemAnalysis,
    VisionAnalysis,
    ObjectiveAnalysis,
    LaningAnalysis,
    PlayerAnalysis,
    MatchAnalysis,
    MatchEvent,
)
from app.utils.hero_names import resolve_hero_name
from app.utils.item_names import resolve_item_name, resolve_rank_name
from app.services.verdict import build_match_verdict

LANE_NAMES = {1: "优势路", 2: "中路", 3: "劣势路", 4: "野区"}

KEY_ITEM_THRESHOLDS = {
    "blink": 16,
    "black_king_bar": 22,
    "cyclone": 18,
    "force_staff": 18,
    "pipe": 20,
    "crimson_guard": 20,
    "guardian_greaves": 18,
    "ultimate_scepter": 30,
    "aghanims_scepter": 30,
    "manta": 22,
    "sheepstick": 30,
    "refresher": 35,
    "satanic": 35,
    "assault": 30,
    "shivas_guard": 30,
    "lotus_orb": 20,
}

OBJECTIVE_TYPE_LABELS = {
    "CHAT_MESSAGE_ROSHAN_KILL": ("roshan", "肉山"),
    "CHAT_MESSAGE_MINIBOSS_KILL": ("tormentor", "痛苦魔方"),
    "CHAT_MESSAGE_FIRSTBLOOD": ("first_blood", "一血"),
    "CHAT_MESSAGE_AEGIS": ("aegis", "不朽盾"),
}


class DataProcessor:
    def __init__(
        self,
        hero_map: Dict[int, str],
        item_map: Dict[int, str],
        hero_roles: Dict[int, List[str]] = None,
        matchups: Dict[int, Dict[int, float]] = None,
    ):
        self.hero_map = hero_map
        self.item_map = item_map
        self.hero_roles = hero_roles or {}
        self.matchups = matchups or {}

    def process_match(self, raw: RawMatch, parse_status: ParseStatus) -> MatchAnalysis:
        objectives = raw.objectives or []
        teamfights = raw.teamfights or []
        players = [
            self._process_player(p, raw, parse_status, objectives, teamfights)
            for p in raw.players
        ]
        if parse_status == ParseStatus.PARSED:
            self._apply_lane_evaluation(players, raw)
        timeline = self._build_timeline(raw, players, parse_status)

        analysis = MatchAnalysis(
            match_id=raw.match_id,
            duration_minutes=raw.duration / 60.0,
            radiant_win=raw.radiant_win,
            parse_status=parse_status,
            players=players,
            analyzed_at=datetime.utcnow(),
            timeline=timeline,
        )
        if parse_status == ParseStatus.PARSED:
            analysis.verdict = build_match_verdict(analysis)
        return analysis

    def _process_player(
        self,
        p: RawPlayer,
        match: RawMatch,
        parse_status: ParseStatus,
        objectives: list,
        teamfights: list,
    ) -> PlayerAnalysis:
        team = "天辉" if p.player_slot < 128 else "夜魇"
        hero_name = resolve_hero_name(p.hero_id, self.hero_map)
        rank_name = resolve_rank_name(p.rank_tier)
        is_parsed = parse_status == ParseStatus.PARSED
        key_deaths, teamfight_deaths = self._death_metrics(
            p.deaths_log, teamfights, is_parsed
        )
        death_timing_available = bool(
            is_parsed and p.deaths_log is not None and teamfights
        )
        if p.buyback_count is not None:
            buyback_count = int(p.buyback_count)
        else:
            buyback_count = len(p.buyback_log or [])

        economy = self._process_economy(p)
        teamfight = self._process_teamfight(p, is_parsed)
        items = self._process_items(p)
        vision = self._process_vision(p, is_parsed)
        obj = self._process_objectives(p, match, objectives, is_parsed)
        laning = self._process_laning(p, is_parsed)

        return PlayerAnalysis(
            player_slot=p.player_slot,
            team=team,
            hero_name=hero_name,
            personaname=p.personaname,
            rank_tier=p.rank_tier,
            rank_name=rank_name,
            hero_roles=self.hero_roles.get(p.hero_id, []),
            economy=economy,
            teamfight=teamfight,
            items=items,
            vision=vision,
            objectives=obj,
            laning=laning,
            key_deaths=key_deaths,
            teamfight_deaths=teamfight_deaths,
            death_timing_available=death_timing_available,
            buyback_count=buyback_count,
            parse_status=parse_status,
        )

    def _death_metrics(self, death_log, teamfights: list, is_parsed: bool):
        if not is_parsed or not death_log:
            return 0, 0

        death_times = []
        for entry in death_log:
            if not isinstance(entry, dict):
                continue
            try:
                death_times.append(int(entry.get("time")))
            except (TypeError, ValueError):
                continue

        windows = []
        for fight in teamfights:
            if not isinstance(fight, dict):
                continue
            try:
                start = int(fight.get("start"))
                end = int(fight.get("end"))
            except (TypeError, ValueError):
                continue
            if end >= start:
                windows.append((start, end))
        windows.sort()

        pre_fight = 0
        early_fight = 0
        during_fight = 0
        for death_time in death_times:
            for start, end in windows:
                if start - 10 <= death_time < start:
                    pre_fight += 1
                    break
                if start <= death_time <= start + 10:
                    early_fight += 1
                    break
                if start <= death_time <= end:
                    during_fight += 1
                    break

        key_deaths = pre_fight + early_fight
        teamfight_deaths = pre_fight + early_fight + during_fight
        return key_deaths, teamfight_deaths

    def _value_at(self, timeline, minute: int) -> Optional[int]:
        if not timeline:
            return None
        try:
            index = min(max(int(minute), 0), len(timeline) - 1)
            return int(timeline[index])
        except (TypeError, ValueError):
            return None

    def _physical_lane(self, player: RawPlayer) -> Optional[int]:
        if player.lane in (1, 2, 3):
            return player.lane
        radiant = player.player_slot < 128
        if player.lane_role == 2:
            return 2
        if player.lane_role == 1:
            return 1 if radiant else 3
        if player.lane_role == 3:
            return 3 if radiant else 1
        return None

    def _apply_lane_evaluation(
        self, players: List[PlayerAnalysis], raw: RawMatch
    ) -> None:
        by_slot = {player.player_slot: player for player in players}

        for raw_player in raw.players:
            target = by_slot.get(raw_player.player_slot)
            if target is None or not target.laning.available:
                continue
            lane = self._physical_lane(raw_player)
            if lane is None:
                continue

            is_radiant = raw_player.player_slot < 128
            opponents = [
                other
                for other in raw.players
                if (other.player_slot < 128) != is_radiant
                and self._physical_lane(other) == lane
            ]
            if not opponents:
                continue

            target.laning.opponents = [
                resolve_hero_name(other.hero_id, self.hero_map)
                for other in opponents
            ]

            own_gold = self._value_at(raw_player.gold_t, 10)
            own_xp = self._value_at(raw_player.xp_t, 10)
            own_lh = self._value_at(raw_player.lh_t, 10)
            opp_gold = [
                value for value in (
                    self._value_at(other.gold_t, 10) for other in opponents
                ) if value is not None
            ]
            opp_xp = [
                value for value in (
                    self._value_at(other.xp_t, 10) for other in opponents
                ) if value is not None
            ]
            opp_lh = [
                value for value in (
                    self._value_at(other.lh_t, 10) for other in opponents
                ) if value is not None
            ]

            if own_gold is not None and opp_gold:
                target.laning.gold_diff_10 = int(round(own_gold - sum(opp_gold) / len(opp_gold)))
            if own_xp is not None and opp_xp:
                target.laning.xp_diff_10 = int(round(own_xp - sum(opp_xp) / len(opp_xp)))
            if own_lh is not None and opp_lh:
                target.laning.lh_diff_10 = int(round(own_lh - sum(opp_lh) / len(opp_lh)))

            matchup = self.matchups.get(raw_player.hero_id) or {}
            rates = [
                matchup[other.hero_id]
                for other in opponents
                if other.hero_id in matchup
            ]
            if rates:
                target.laning.matchup_score = round(sum(rates) / len(rates), 1)

            components = []
            if target.laning.gold_diff_10 is not None:
                components.append((
                    0.5,
                    max(0.0, min(100.0, 50 + target.laning.gold_diff_10 / 2500 * 50)),
                ))
            if target.laning.xp_diff_10 is not None:
                components.append((
                    0.3,
                    max(0.0, min(100.0, 50 + target.laning.xp_diff_10 / 2500 * 50)),
                ))
            if target.laning.lh_diff_10 is not None:
                components.append((
                    0.2,
                    max(0.0, min(100.0, 50 + target.laning.lh_diff_10 / 25 * 50)),
                ))

            if not components:
                continue
            total_weight = sum(weight for weight, _score in components)
            performance = sum(
                weight * score for weight, score in components
            ) / total_weight

            if target.laning.matchup_score is not None:
                lane_score = performance * 0.65 + target.laning.matchup_score * 0.35
            else:
                lane_score = performance
            target.laning.lane_score = round(lane_score, 1)

            summary_parts = []
            if target.laning.gold_diff_10 is not None:
                diff = target.laning.gold_diff_10
                if diff > 400:
                    summary_parts.append(f"对线经济领先 +{diff}")
                elif diff < -400:
                    summary_parts.append(f"对线经济落后 {diff}")
                else:
                    summary_parts.append("对线经济基本持平")
            if target.laning.matchup_score is not None:
                if target.laning.matchup_score < 45:
                    summary_parts.append(
                        f"对位被克制（胜率 {target.laning.matchup_score:.0f}%）"
                    )
                elif target.laning.matchup_score > 55:
                    summary_parts.append(
                        f"对位有优势（胜率 {target.laning.matchup_score:.0f}%）"
                    )
            target.laning.summary = "；".join(summary_parts) or None

    def _team_from_value(self, value) -> Optional[str]:
        if value == 2:
            return "天辉"
        if value == 3:
            return "夜魇"
        return None

    def _team_from_slot(self, slot) -> Optional[str]:
        if slot is None:
            return None
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            return None
        return "天辉" if slot < 128 else "夜魇"

    def _building_label(self, key: str) -> str:
        key = key or ""
        side = "天辉" if "goodguys" in key else "夜魇" if "badguys" in key else ""
        lane = "中路" if "_mid" in key else "上路" if "_top" in key else "下路" if "_bot" in key else ""
        if "rax" in key:
            structure = "兵营"
        elif "tower" in key:
            structure = "防御塔"
        else:
            structure = "建筑"
        tier = ""
        for level, label in (("tower1", "一塔"), ("tower2", "二塔"), ("tower3", "三塔"), ("tower4", "四塔")):
            if level in key:
                tier = label
                break
        return f"{side}{lane}{tier or structure}"

    def _build_timeline(
        self,
        raw: RawMatch,
        players: List[PlayerAnalysis],
        parse_status: ParseStatus,
    ) -> List[MatchEvent]:
        if parse_status != ParseStatus.PARSED:
            return []

        events: List[MatchEvent] = []

        def add_event(
            time_value,
            event_type: str,
            type_label: str,
            label: str,
            team: Optional[str] = None,
            player_slot: Optional[int] = None,
            hero_name: Optional[str] = None,
            detail: Optional[str] = None,
        ) -> None:
            try:
                seconds = int(time_value)
            except (TypeError, ValueError):
                return
            if seconds < 0:
                return
            events.append(
                MatchEvent(
                    time=seconds,
                    time_str=self._format_time(seconds),
                    type=event_type,
                    type_label=type_label,
                    label=label,
                    team=team,
                    player_slot=player_slot,
                    hero_name=hero_name,
                    detail=detail,
                )
            )

        for objective in raw.objectives or []:
            if not isinstance(objective, dict):
                continue
            obj_type = objective.get("type", "")
            time_value = objective.get("time")
            team_value = self._team_from_value(objective.get("team"))
            slot_team = self._team_from_slot(objective.get("player_slot"))
            team = team_value or slot_team
            player_slot = objective.get("player_slot")
            hero_name = None
            if player_slot is not None:
                try:
                    raw_player = next(
                        (p for p in raw.players if p.player_slot == int(player_slot)),
                        None,
                    )
                except (TypeError, ValueError):
                    raw_player = None
                if raw_player:
                    hero_name = resolve_hero_name(raw_player.hero_id, self.hero_map)

            if obj_type in OBJECTIVE_TYPE_LABELS:
                event_type, label = OBJECTIVE_TYPE_LABELS[obj_type]
                add_event(
                    time_value,
                    event_type,
                    label,
                    label,
                    team=team,
                    player_slot=player_slot,
                    hero_name=hero_name,
                )
            elif obj_type == "building_kill":
                add_event(
                    time_value,
                    "tower",
                    "建筑",
                    self._building_label(objective.get("key", "")),
                    team=slot_team,
                    player_slot=player_slot,
                    hero_name=hero_name,
                )

        for raw_player in raw.players:
            hero_name = resolve_hero_name(raw_player.hero_id, self.hero_map)
            team = self._team_from_slot(raw_player.player_slot)
            for entry in raw_player.buyback_log or []:
                if isinstance(entry, dict):
                    add_event(
                        entry.get("time"),
                        "buyback",
                        "买活",
                        "买活",
                        team=team,
                        player_slot=raw_player.player_slot,
                        hero_name=hero_name,
                    )

        for player in players:
            for item in player.items.key_items:
                add_event(
                    item.get("time"),
                    "item",
                    "关键装备",
                    item.get("item", ""),
                    team=player.team,
                    player_slot=player.player_slot,
                    hero_name=player.hero_name,
                    detail=f"目标 {item.get('target_minutes')} 分钟",
                )

        events.sort(key=lambda event: (event.time, event.type))
        return events[:300]

    def _process_economy(self, p: RawPlayer) -> EconomyAnalysis:
        bm = p.benchmarks
        gpm_pct = None
        lh_pct = None
        if bm:
            if bm.gold_per_min:
                pct = bm.gold_per_min.get("pct")
                if pct is not None:
                    gpm_pct = round(pct * 100, 1)
            if bm.last_hits_per_min:
                pct = bm.last_hits_per_min.get("pct")
                if pct is not None:
                    lh_pct = round(pct * 100, 1)

        gold_timeline = None
        gold_timeline_step = 1
        if p.gold_t:
            gold_timeline = self._normalize_timeline(p.gold_t)
            if len(gold_timeline) > 24:
                gold_timeline_step = 2
                gold_timeline = self._sample_timeline(gold_timeline, step=gold_timeline_step)

        return EconomyAnalysis(
            gpm=p.gold_per_min,
            xpm=p.xp_per_min,
            last_hits=p.last_hits,
            denies=p.denies,
            net_worth=p.net_worth or 0,
            gold_spent=p.gold_spent or 0,
            gpm_benchmark_pct=gpm_pct,
            lh_benchmark_pct=lh_pct,
            gold_timeline=gold_timeline,
            gold_timeline_step=gold_timeline_step,
        )

    def _process_teamfight(self, p: RawPlayer, is_parsed: bool) -> TeamfightAnalysis:
        deaths = p.deaths or 0
        kills = p.kills or 0
        assists = p.assists or 0
        kda = (kills + assists) / max(deaths, 1)

        bm = p.benchmarks
        dmg_pct = None
        if bm and bm.hero_damage_per_min:
            pct = bm.hero_damage_per_min.get("pct")
            if pct is not None:
                dmg_pct = round(pct * 100, 1)

        return TeamfightAnalysis(
            participation_rate=p.teamfight_participation if is_parsed else None,
            hero_damage=p.hero_damage or 0,
            hero_damage_benchmark_pct=dmg_pct,
            tower_damage=p.tower_damage or 0,
            hero_healing=p.hero_healing or 0,
            kills=kills,
            deaths=deaths,
            assists=assists,
            kda=round(kda, 2),
            available=is_parsed or (p.hero_damage is not None),
        )

    def _process_items(self, p: RawPlayer) -> ItemAnalysis:
        item_ids = [p.item_0, p.item_1, p.item_2, p.item_3, p.item_4, p.item_5]
        final_items = [
            resolve_item_name(iid, self.item_map)
            for iid in item_ids
            if iid != 0
        ]

        purchase_timeline = None
        has_timeline = False
        if p.purchase_log:
            has_timeline = True
            purchase_timeline = [
                {
                    "time": entry.get("time", 0),
                    "time_str": self._format_time(entry.get("time", 0)),
                    "item_key": entry.get("key", ""),
                    "item": resolve_item_name(entry.get("key", ""), self.item_map),
                }
                for entry in p.purchase_log
            ]

        key_items = []
        seen_items = set()
        if p.purchase_log:
            for entry in p.purchase_log:
                if not isinstance(entry, dict):
                    continue
                item_key = entry.get("key", "")
                threshold = KEY_ITEM_THRESHOLDS.get(item_key)
                if threshold is None or item_key in seen_items:
                    continue
                try:
                    time_value = int(entry.get("time", 0))
                except (TypeError, ValueError):
                    continue
                if time_value < 0:
                    continue
                seen_items.add(item_key)
                minutes = time_value / 60.0
                timing_score = max(
                    0.0,
                    min(100.0, 100.0 - max(0.0, minutes - threshold) * 8.0),
                )
                key_items.append({
                    "item_key": item_key,
                    "item": resolve_item_name(item_key, self.item_map),
                    "time": time_value,
                    "time_str": self._format_time(time_value),
                    "target_minutes": threshold,
                    "score": round(timing_score, 1),
                })
        key_items.sort(key=lambda item: item["time"])
        key_item_score = (
            round(
                sum(item["score"] for item in key_items) / len(key_items),
                1,
            )
            if key_items
            else None
        )

        return ItemAnalysis(
            final_items=final_items,
            aghanims_scepter=bool(p.aghanims_scepter),
            aghanims_shard=bool(p.aghanims_shard),
            moonshard=bool(p.moonshard),
            purchase_timeline=purchase_timeline,
            has_timeline=has_timeline,
            key_items=key_items,
            key_item_score=key_item_score,
        )

    def _process_vision(self, p: RawPlayer, is_parsed: bool) -> VisionAnalysis:
        available = is_parsed and (p.obs_placed is not None or p.sen_placed is not None)
        return VisionAnalysis(
            obs_placed=p.obs_placed,
            sen_placed=p.sen_placed,
            obs_killed=p.obs_killed,
            sen_killed=p.sen_killed,
            available=available,
        )

    def _process_objectives(
        self, p: RawPlayer, match: RawMatch, objectives: list, is_parsed: bool
    ) -> ObjectiveAnalysis:
        if not is_parsed or not objectives:
            return ObjectiveAnalysis(available=False)

        team_value = 2 if p.player_slot < 128 else 3
        roshan_kills = 0
        tormentor_kills = 0
        wisdom_runes = 0
        lotus_uses = 0

        for obj in objectives:
            obj_type = obj.get("type", "")
            obj_team = obj.get("team", -1)
            slot = obj.get("player_slot")

            if obj_type == "CHAT_MESSAGE_ROSHAN_KILL":
                if obj_team == team_value:
                    roshan_kills += 1
            elif obj_type in {
                "CHAT_MESSAGE_TORMENTOR_KILL",
                "CHAT_MESSAGE_MINIBOSS_KILL",
            }:
                if obj_team == team_value:
                    tormentor_kills += 1
            elif obj_type == "CHAT_MESSAGE_RUNE_PICKUP" and slot == p.player_slot:
                key = obj.get("key", "")
                if key == "wisdom":
                    wisdom_runes += 1
                elif key == "lotus":
                    lotus_uses += 1

        return ObjectiveAnalysis(
            roshan_kills=roshan_kills,
            tormentor_kills=tormentor_kills,
            wisdom_runes=wisdom_runes,
            lotus_pool_uses=lotus_uses,
            available=True,
        )

    def _process_laning(self, p: RawPlayer, is_parsed: bool) -> LaningAnalysis:
        if not is_parsed:
            return LaningAnalysis(available=False)

        lane_name = None
        if p.lane_role is not None:
            lane_name = LANE_NAMES.get(p.lane_role)
        elif p.lane is not None:
            lane_name = LANE_NAMES.get(p.lane)

        if p.is_roaming:
            lane_name = "游走"

        return LaningAnalysis(
            lane_name=lane_name,
            is_roaming=p.is_roaming,
            camps_stacked=p.camps_stacked,
            creeps_stacked=p.creeps_stacked,
            actions_per_min=p.actions_per_min,
            available=True,
        )

    def _sample_timeline(self, timeline: List[int], step: int = 5) -> List[int]:
        return [timeline[i] for i in range(0, len(timeline), step)]

    def _normalize_timeline(self, timeline: List[int]) -> List[int]:
        return [int(value) for value in timeline if value is not None]

    def _format_time(self, seconds: int) -> str:
        if seconds < 0:
            return f"-{abs(seconds) // 60}:{abs(seconds) % 60:02d}"
        return f"{seconds // 60}:{seconds % 60:02d}"
