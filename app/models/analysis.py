from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from .match import ParseStatus


class EconomyAnalysis(BaseModel):
    gpm: int
    xpm: int
    last_hits: int
    denies: int
    net_worth: int
    gold_spent: int
    gpm_benchmark_pct: Optional[float] = None
    lh_benchmark_pct: Optional[float] = None
    gold_timeline: Optional[List[int]] = None
    gold_timeline_step: int = 1


class TeamfightAnalysis(BaseModel):
    participation_rate: Optional[float] = None
    hero_damage: int
    hero_damage_benchmark_pct: Optional[float] = None
    tower_damage: int
    hero_healing: int
    kills: int
    deaths: int
    assists: int
    kda: float
    available: bool


class ItemAnalysis(BaseModel):
    final_items: List[str]
    aghanims_scepter: bool
    aghanims_shard: bool
    moonshard: bool
    purchase_timeline: Optional[List[dict]] = None
    has_timeline: bool


class VisionAnalysis(BaseModel):
    obs_placed: Optional[int] = None
    sen_placed: Optional[int] = None
    obs_killed: Optional[int] = None
    sen_killed: Optional[int] = None
    available: bool


class ObjectiveAnalysis(BaseModel):
    roshan_kills: int = 0
    tormentor_kills: int = 0
    wisdom_runes: int = 0
    lotus_pool_uses: int = 0
    available: bool


class LaningAnalysis(BaseModel):
    lane_name: Optional[str] = None
    is_roaming: Optional[bool] = None
    camps_stacked: Optional[int] = None
    creeps_stacked: Optional[int] = None
    actions_per_min: Optional[int] = None
    available: bool


class AISuggestions(BaseModel):
    economy_tips: List[str] = []
    teamfight_tips: List[str] = []
    item_tips: List[str] = []
    vision_tips: List[str] = []
    laning_tips: List[str] = []
    overall_summary: str = ""
    priority_improvement: str = ""


class PlayerAnalysis(BaseModel):
    player_slot: int
    team: str
    hero_name: str
    personaname: Optional[str] = None
    rank_tier: Optional[int] = None
    rank_name: str = ""
    economy: EconomyAnalysis
    teamfight: TeamfightAnalysis
    items: ItemAnalysis
    vision: VisionAnalysis
    objectives: ObjectiveAnalysis
    laning: LaningAnalysis
    parse_status: ParseStatus
    ai_suggestions: Optional[AISuggestions] = None


class MatchAnalysis(BaseModel):
    match_id: int
    duration_minutes: float
    radiant_win: bool
    parse_status: ParseStatus
    players: List[PlayerAnalysis]
    match_summary: Optional[str] = None
    analyzed_at: datetime
    cache_version: int = 3
