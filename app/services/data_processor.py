from datetime import datetime
from typing import Dict, List

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
)
from app.utils.hero_names import resolve_hero_name
from app.utils.item_names import resolve_item_name, resolve_rank_name
from app.services.verdict import build_match_verdict

LANE_NAMES = {1: "优势路", 2: "中路", 3: "劣势路", 4: "野区"}


class DataProcessor:
    def __init__(self, hero_map: Dict[int, str], item_map: Dict[int, str]):
        self.hero_map = hero_map
        self.item_map = item_map

    def process_match(self, raw: RawMatch, parse_status: ParseStatus) -> MatchAnalysis:
        objectives = raw.objectives or []
        players = [
            self._process_player(p, raw, parse_status, objectives)
            for p in raw.players
        ]
        analysis = MatchAnalysis(
            match_id=raw.match_id,
            duration_minutes=raw.duration / 60.0,
            radiant_win=raw.radiant_win,
            parse_status=parse_status,
            players=players,
            analyzed_at=datetime.utcnow(),
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
    ) -> PlayerAnalysis:
        team = "天辉" if p.player_slot < 128 else "夜魇"
        hero_name = resolve_hero_name(p.hero_id, self.hero_map)
        rank_name = resolve_rank_name(p.rank_tier)
        is_parsed = parse_status == ParseStatus.PARSED

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
            economy=economy,
            teamfight=teamfight,
            items=items,
            vision=vision,
            objectives=obj,
            laning=laning,
            parse_status=parse_status,
        )

    def _process_economy(self, p: RawPlayer) -> EconomyAnalysis:
        bm = p.benchmarks
        gpm_pct = None
        lh_pct = None
        if bm:
            if bm.gold_per_min:
                gpm_pct = round(bm.gold_per_min.get("pct", 0) * 100, 1)
            if bm.last_hits_per_min:
                lh_pct = round(bm.last_hits_per_min.get("pct", 0) * 100, 1)

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
            dmg_pct = round(bm.hero_damage_per_min.get("pct", 0) * 100, 1)

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

        return ItemAnalysis(
            final_items=final_items,
            aghanims_scepter=bool(p.aghanims_scepter),
            aghanims_shard=bool(p.aghanims_shard),
            moonshard=bool(p.moonshard),
            purchase_timeline=purchase_timeline,
            has_timeline=has_timeline,
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

        team_slot = 0 if p.player_slot < 128 else 1
        roshan_kills = 0
        tormentor_kills = 0
        wisdom_runes = 0
        lotus_uses = 0

        for obj in objectives:
            obj_type = obj.get("type", "")
            obj_team = obj.get("team", -1)
            slot = obj.get("player_slot")

            if obj_type == "CHAT_MESSAGE_ROSHAN_KILL":
                if obj_team == team_slot:
                    roshan_kills += 1
            elif obj_type == "CHAT_MESSAGE_TORMENTOR_KILL":
                if obj_team == team_slot:
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
        if p.lane is not None:
            lane_name = LANE_NAMES.get(p.lane)
        elif p.lane_role is not None:
            lane_name = LANE_NAMES.get(p.lane_role)

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
