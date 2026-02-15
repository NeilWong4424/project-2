import pytest

import app.telegram_handler as th


def test_extract_command_names_includes_command():
    names = th._extract_command_names(th.TelegramBotHandler.HELP_MENU)
    assert "command" in names


def test_command_names_excludes_system_command():
    assert "command" not in th.TelegramBotHandler.COMMAND_NAMES


@pytest.mark.asyncio
async def test_check_verification_caches_verified(monkeypatch):
    calls = {"count": 0}

    async def fake_check_is_owner(user_id: str):
        calls["count"] += 1
        return {"is_owner": True, "club_ref": "club/x", "club_name": "Test FC"}

    monkeypatch.setattr(th, "check_is_owner", fake_check_is_owner)

    handler = th.TelegramBotHandler("token", agent=None, session_service=None)

    res1 = await handler._check_verification("123")
    res2 = await handler._check_verification("123")

    assert calls["count"] == 1
    assert res1["club_ref"] == "club/x"
    assert res2["club_ref"] == "club/x"


@pytest.mark.asyncio
async def test_check_verification_negative_cache(monkeypatch):
    calls = {"count": 0}

    async def fake_check_is_owner(user_id: str):
        calls["count"] += 1
        return {"is_owner": False}

    monkeypatch.setattr(th, "check_is_owner", fake_check_is_owner)

    now = 1_000_000.0
    monkeypatch.setattr(th.time, "time", lambda: now)

    handler = th.TelegramBotHandler("token", agent=None, session_service=None)

    res1 = await handler._check_verification("456")
    res2 = await handler._check_verification("456")

    assert res1 is None
    assert res2 is None
    assert calls["count"] == 1

    # Move past the TTL and ensure it checks again.
    monkeypatch.setattr(th.time, "time", lambda: now + th._UNVERIFIED_CACHE_TTL + 1)
    res3 = await handler._check_verification("456")
    assert res3 is None
    assert calls["count"] == 2
