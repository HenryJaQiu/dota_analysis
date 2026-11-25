from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from enum import Enum


class ParseStatus(str, Enum):
    NOT_PARSED = "not_parsed"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


class Benchmarks(BaseModel):
    gold_per_min: Optional[Dict[str, Any]] = None
    xp_per_min: Optional[Dict[str, Any]] = None
    kills_per_min: Optional[Dict[str, Any]] = None
    last_hits_per_min: Optional[Dict[str, Any]] = None
    hero_damage_per_min: Optional[Dict[str, Any]] = None
    hero_healing_per_min: Optional[Dict[str, Any]] = None
    tower_damage: Optional[Dict[str, Any]] = None


class RawPlayer(BaseModel):
    account_id: Optional[int] = None
    player_slot: int
    team_number: Optional[int] = None
    hero_id: int
    personaname: Optional[str] = None
    rank_tier: Optional[int] = None
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0
    gold_per_min: int = 0
    xp_per_min: int = 0
    level: int = 1
    net_worth: Optional[int] = None
    gold: Optional[int] = None
    gold_spent: Optional[int] = None
    hero_damage: Optional[int] = None
    tower_damage: Optional[int] = None
    hero_healing: Optional[int] = None
    aghanims_scepter: Optional[int] = None
    aghanims_shard: Optional[int] = None
    moonshard: Optional[int] = None
    item_0: int = 0
    item_1: int = 0
    item_2: int = 0
    item_3: int = 0
    item_4: int = 0
    item_5: int = 0
    backpack_0: int = 0
    backpack_1: int = 0
    backpack_2: int = 0
    item_neutral: int = 0
    ability_upgrades_arr: Optional[List[int]] = None
    benchmarks: Optional[Benchmarks] = None
    kda: Optional[float] = None
    # Parse-dependent fields
    obs_placed: Optional[int] = None
    sen_placed: Optional[int] = None
    obs_killed: Optional[int] = None
    sen_killed: Optional[int] = None
    camps_stacked: Optional[int] = None
    creeps_stacked: Optional[int] = None
    teamfight_participation: Optional[float] = None
    gold_t: Optional[List[int]] = None
    xp_t: Optional[List[int]] = None
    lane: Optional[int] = None
    lane_role: Optional[int] = None
    is_roaming: Optional[bool] = None
    purchase_log: Optional[List[Dict[str, Any]]] = None
    deaths_log: Optional[List[Dict[str, Any]]] = None
    actions_per_min: Optional[int] = None
    life_state_dead: Optional[int] = None
    total_gold: Optional[int] = None
    total_xp: Optional[int] = None
    radiant_win: Optional[bool] = None

    model_config = ConfigDict(extra="allow")


class RawMatch(BaseModel):
    match_id: int
    radiant_win: bool
    duration: int
    start_time: Optional[int] = None
    game_mode: Optional[int] = None
    patch: Optional[int] = None
    players: List[RawPlayer]
    # Parse-dependent
    teamfights: Optional[List[Dict[str, Any]]] = None
    objectives: Optional[List[Dict[str, Any]]] = None
    radiant_gold_adv: Optional[List[int]] = None
    radiant_xp_adv: Optional[List[int]] = None
    picks_bans: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(extra="allow")
