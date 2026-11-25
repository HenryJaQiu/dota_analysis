import pytest

from app.services.follows import (
    STEAM64_BASE,
    FollowError,
    FollowStore,
    parse_steam_input,
)


def test_friend_code_and_steamid64():
    account_id = 123456789
    parsed = parse_steam_input(str(account_id))
    assert parsed.account_id == account_id
    assert parsed.steam_id64 == STEAM64_BASE + account_id

    parsed64 = parse_steam_input(str(STEAM64_BASE + account_id))
    assert parsed64.account_id == account_id
    assert parsed64.source == "steam64"


def test_steam2_and_steam3_formats():
    assert parse_steam_input("STEAM_0:1:61728394").account_id == 123456789
    assert parse_steam_input("[U:1:123456789]").account_id == 123456789


def test_profile_urls():
    steam_id64 = STEAM64_BASE + 123456789
    parsed = parse_steam_input(f"https://steamcommunity.com/profiles/{steam_id64}/")
    assert parsed.account_id == 123456789

    vanity = parse_steam_input("https://steamcommunity.com/id/example_name/")
    assert vanity.account_id is None
    assert vanity.vanity == "example_name"


def test_invalid_inputs():
    with pytest.raises(FollowError):
        parse_steam_input("")
    with pytest.raises(FollowError):
        parse_steam_input("0")
    with pytest.raises(FollowError):
        parse_steam_input("https://evil.example.com/profiles/76561197960265729")
    with pytest.raises(FollowError):
        parse_steam_input("not a valid vanity name!")


def test_follow_store_roundtrip(tmp_path):
    store = FollowStore(str(tmp_path / "follows.json"))
    store.add({
        "account_id": 123,
        "steam_id64": str(STEAM64_BASE + 123),
        "personaname": "tester",
        "matches": [],
    })
    players = store.list()
    assert len(players) == 1
    assert players[0]["account_id"] == 123

    store.update(123, personaname="updated", matches=[{"match_id": 1}])
    updated = store.list()[0]
    assert updated["personaname"] == "updated"
    assert updated["matches"] == [{"match_id": 1}]

    assert store.remove(123) is True
    assert store.list() == []
