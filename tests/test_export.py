import os

from fastapi.testclient import TestClient

from app.services import cache as cache_module
import app.routers.analysis as analysis_router
from tests.test_verdict import make_match
from app.services.verdict import build_match_verdict
import main


def test_static_export_is_self_contained(tmp_path, monkeypatch):
    match = make_match()
    match.match_id = 777
    match.verdict = build_match_verdict(match)

    cache = cache_module.CacheManager()
    cache.cache_dir = str(tmp_path / "matches")
    cache.raw_dir = str(tmp_path / "raw")
    os.makedirs(cache.cache_dir, exist_ok=True)
    os.makedirs(cache.raw_dir, exist_ok=True)
    cache.set(777, match)

    monkeypatch.setattr(analysis_router, "get_cache", lambda: cache)
    client = TestClient(main.app)
    response = client.get("/match/777/export")

    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    text = response.text
    assert "<style>" in text
    assert "window.MATCH_DATA" in text
    assert "verdict-section" in text
    assert "timeline-section" in text
    assert "settings-modal" not in text
    assert "/static/css/style.css" not in text
    assert "settings.js" not in text

    # Static reports must expose every player without relying on tab JavaScript.
    assert text.count('class="player-panel') == 10
    assert text.count('class="share-player-link"') == 10
    assert text.count('class="share-section-title"') == 60
    assert text.count('href="#panel-') == 20
    assert text.count('href="#players"') == 10
    assert 'id="players"' in text
    assert 'onclick="switchPlayer' not in text
    assert ".share-page .player-panel" in text
