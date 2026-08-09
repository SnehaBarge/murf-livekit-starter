from types import SimpleNamespace

import pytest
from livekit.agents import llm

import agent as agent_module
from agent import Assistant
from prompts import SYSTEM_PROMPT


class FakeContext:
    def __init__(self, identity: str):
        self.session = SimpleNamespace(
            room_io=SimpleNamespace(
                linked_participant=SimpleNamespace(identity=identity)
            )
        )


@pytest.fixture
def memory_store(monkeypatch):
    store = {}

    def fake_get_farmer(user_id: str):
        return store.get(user_id)

    def fake_save_farmer(user_id: str, **profile):
        store[user_id] = {
            **profile,
            "user_id": user_id,
            "last_interaction": "2026-08-09T00:00:00+00:00",
        }

    monkeypatch.setattr(agent_module, "get_farmer", fake_get_farmer)
    monkeypatch.setattr(agent_module, "save_farmer", fake_save_farmer)
    return store


async def grant_consent(assistant: Assistant) -> None:
    turn_context = llm.ChatContext(
        [
            llm.ChatMessage(
                role="assistant",
                content=[
                    "May I remember your name and farm information for next time?"
                ],
            )
        ]
    )
    await assistant.on_user_turn_completed(
        turn_context,
        llm.ChatMessage(role="user", content=["Yes, you can remember it."]),
    )


@pytest.mark.asyncio
async def test_new_caller_lookup_returns_none(memory_store):
    result = await Assistant().lookup_farmer(FakeContext("stable-user-1"))

    assert result == "No saved farmer profile was found for this caller."


@pytest.mark.asyncio
async def test_explicit_consent_saves_profile(memory_store):
    assistant = Assistant()
    await grant_consent(assistant)

    result = await assistant.save_farmer(
        FakeContext("stable-user-1"),
        "Ramesh",
        crops_grown="cotton",
        land_size="4 acres",
        district="Nashik",
        irrigation_type="drip irrigation",
    )

    assert result == "The farmer profile was saved for future conversations."
    assert memory_store["stable-user-1"]["name"] == "Ramesh"
    assert memory_store["stable-user-1"]["crops_grown"] == "cotton"
    assert memory_store["stable-user-1"]["land_size"] == "4 acres"
    assert memory_store["stable-user-1"]["district"] == "Nashik"
    assert memory_store["stable-user-1"]["irrigation_type"] == "drip irrigation"


@pytest.mark.asyncio
async def test_explicit_refusal_does_not_save(memory_store):
    assistant = Assistant()
    turn_context = llm.ChatContext(
        [
            llm.ChatMessage(
                role="assistant",
                content=["May I save your farm information for next time?"],
            )
        ]
    )
    await assistant.on_user_turn_completed(
        turn_context,
        llm.ChatMessage(role="user", content=["No, do not save it."]),
    )

    result = await assistant.save_farmer(
        FakeContext("stable-user-1"), "Ramesh", crops_grown="cotton"
    )

    assert result == "I will not save your information unless you explicitly agree."
    assert memory_store == {}


@pytest.mark.asyncio
async def test_same_stable_id_retrieves_profile_on_second_call(memory_store):
    first_call = Assistant()
    await grant_consent(first_call)
    await first_call.save_farmer(
        FakeContext("stable-user-1"),
        "Ramesh",
        crops_grown="cotton",
        land_size="4 acres",
        district="Nashik",
        irrigation_type="drip irrigation",
    )

    second_call = Assistant()
    result = await second_call.lookup_farmer(FakeContext("stable-user-1"))

    assert "name=Ramesh" in result
    assert "crops=cotton" in result
    assert "land size=4 acres" in result
    assert "district=Nashik" in result
    assert "irrigation type=drip irrigation" in result


def test_returning_greeting_requires_name_and_saved_facts():
    assert "greet the farmer by name" in SYSTEM_PROMPT
    assert "welcome back" in SYSTEM_PROMPT
    assert "your cotton farm in Nashik" in SYSTEM_PROMPT
