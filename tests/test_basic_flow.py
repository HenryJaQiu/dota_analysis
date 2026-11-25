import asyncio
import os

from app.models.match import ParseStatus, RawMatch, RawPlayer
from app.services import cache as cache_module
import app.routers.analysis as analysis_router


class FakeClient:
    def __init__(self, raw: RawMatch):
        self.raw = raw

    async def fetch_match(self, match_id: int) -> RawMatch:
        return self.raw

    def detect_parse_status(self, raw: RawMatch) -> ParseStatus:
        return ParseStatus.NOT_PARSED


def test_basic_data_is_saved_immediately_and_parse_job_starts(tmp_path, monkeypatch):
    raw = RawMatch(
        match_id=999,
        radiant_win=True,
        duration=2400,
        players=[
            RawPlayer(
                player_slot=0,
                hero_id=1,
                personaname="tester",
                gold_per_min=500,
                xp_per_min=600,
                last_hits=200,
                denies=10,
                net_worth=15000,
                gold_spent=14000,
                kills=5,
                deaths=2,
                assists=5,
                hero_damage=20000,
                tower_damage=2000,
                hero_healing=0,
            )
        ],
    )

    cache = cache_module.CacheManager()
    cache.cache_dir = str(tmp_path / "matches")
    cache.raw_dir = str(tmp_path / "raw")
    os.makedirs(cache.cache_dir, exist_ok=True)
    os.makedirs(cache.raw_dir, exist_ok=True)

    parse_jobs = []

    async def fake_load_maps(client):
        return {1: "主宰"}, {}, {1: ["Carry", "Escape"]}

    async def fake_ensure_parse_job(match_id):
        parse_jobs.append(match_id)
        return {"status": "queued"}

    monkeypatch.setattr(analysis_router, "get_cache", lambda: cache)
    monkeypatch.setattr(analysis_router, "get_client", lambda: FakeClient(raw))
    monkeypatch.setattr(analysis_router, "_load_maps", fake_load_maps)
    monkeypatch.setattr(analysis_router, "_ensure_parse_job", fake_ensure_parse_job)

    asyncio.run(analysis_router._run_analysis_job(999))

    saved = cache.get(999)
    assert saved is not None
    assert saved.parse_status == ParseStatus.NOT_PARSED
    assert saved.verdict is None
    assert saved.players[0].ai_suggestions is None
    assert parse_jobs == [999]

    raw_saved = cache.get_raw(999)
    assert raw_saved is not None
    assert raw_saved["match_id"] == 999
    assert raw_saved["players"][0]["hero_id"] == 1
