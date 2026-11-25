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
    teamfight_gold_delta: int = 0
    teamfight_xp_delta: int = 0
    teamfight_damage: int = 0
    teamfight_healing: int = 0
    teamfight_count: int = 0


class ItemAnalysis(BaseModel):
    final_items: List[str]
    aghanims_scepter: bool
    aghanims_shard: bool
    moonshard: bool
    purchase_timeline: Optional[List[dict]] = None
    has_timeline: bool
    key_items: List[dict] = []
    key_item_score: Optional[float] = None


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
    opponents: List[str] = []
    gold_diff_10: Optional[int] = None
    xp_diff_10: Optional[int] = None
    lh_diff_10: Optional[int] = None
    matchup_score: Optional[float] = None
    matchup_games: Optional[int] = None
    matchup_source: Optional[str] = None
    lane_score: Optional[float] = None
    summary: Optional[str] = None


class AISuggestions(BaseModel):
    economy_tips: List[str] = []
    teamfight_tips: List[str] = []
    item_tips: List[str] = []
    vision_tips: List[str] = []
    laning_tips: List[str] = []
    overall_summary: str = ""
    priority_improvement: str = ""
    # Metadata about the model that produced this review.
    provider: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[datetime] = None
    error: Optional[str] = None


class PlayerAnalysis(BaseModel):
    player_slot: int
    team: str
    hero_name: str
    personaname: Optional[str] = None
    rank_tier: Optional[int] = None
    rank_name: str = ""
    hero_roles: List[str] = []
    economy: EconomyAnalysis
    teamfight: TeamfightAnalysis
    items: ItemAnalysis
    vision: VisionAnalysis
    objectives: ObjectiveAnalysis
    laning: LaningAnalysis
    # Parsed death timing: deaths in a teamfight or just before one.
    key_deaths: int = 0
    teamfight_deaths: int = 0
    death_timing_available: bool = False
    teamfight_data_available: bool = False
    buyback_count: int = 0
    parse_status: ParseStatus
    ai_suggestions: Optional[AISuggestions] = None


class VerdictMetric(BaseModel):
    key: str
    label: str
    value: str
    score: float
    weight: float
    contribution: float
    rank: int = 0
    team_score: Optional[float] = None
    benchmark_score: Optional[float] = None
    note: Optional[str] = None


class PlayerVerdict(BaseModel):
    player_slot: int
    personaname: Optional[str] = None
    hero_name: str
    team: str
    role: str = ""
    score: float = 0.0
    rank: int = 0
    reasons: List[str] = []
    metrics: List[VerdictMetric] = []


class MatchVerdict(BaseModel):
    winner_team: str
    loser_team: str
    best_player: PlayerVerdict
    most_responsible: PlayerVerdict
    winner_rankings: List[PlayerVerdict] = []
    loser_rankings: List[PlayerVerdict] = []
    methodology: str = ""
    profile: str = "balanced"
    profile_label: str = ""
    confidence: float = 0.0
    confidence_label: str = ""
    evidence: List[str] = []


class MatchEvent(BaseModel):
    time: int
    time_str: str
    type: str
    type_label: str
    label: str
    team: Optional[str] = None
    player_slot: Optional[int] = None
    hero_name: Optional[str] = None
    detail: Optional[str] = None


class MatchAnalysis(BaseModel):
    match_id: int
    duration_minutes: float
    radiant_win: bool
    parse_status: ParseStatus
    players: List[PlayerAnalysis]
    match_summary: Optional[str] = None
    analyzed_at: datetime
    verdict: Optional[MatchVerdict] = None
    timeline: List[MatchEvent] = []
    cache_version: int = 4
