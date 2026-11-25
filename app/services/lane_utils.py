"""Small shared helpers for physical lane and lane-role inference."""

from typing import Iterable, Optional, Set, Tuple

from app.models.match import RawPlayer


def physical_lane(player: RawPlayer) -> Optional[int]:
    """Return 1=bottom, 2=mid, 3=top when the lane can be inferred."""
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


def lane_role_for(player: RawPlayer) -> Optional[int]:
    """Return 1=safe, 2=mid, 3=off when the role can be inferred."""
    if player.lane_role in (1, 2, 3):
        return player.lane_role
    lane = physical_lane(player)
    if lane == 2:
        return 2
    radiant = player.player_slot < 128
    if lane == 1:
        return 1 if radiant else 3
    if lane == 3:
        return 3 if radiant else 1
    return None


def build_lane_pairs(players: Iterable[RawPlayer]) -> Set[Tuple[int, int, int]]:
    """Build (hero_id, opponent_hero_id, lane_role) combinations."""
    player_list = list(players)
    pairs: Set[Tuple[int, int, int]] = set()
    for player in player_list:
        lane = physical_lane(player)
        role = lane_role_for(player)
        if lane not in (1, 2, 3) or role not in (1, 2, 3):
            continue
        is_radiant = player.player_slot < 128
        for opponent in player_list:
            if (opponent.player_slot < 128) == is_radiant:
                continue
            if physical_lane(opponent) != lane:
                continue
            pairs.add((int(player.hero_id), int(opponent.hero_id), int(role)))
    return pairs
