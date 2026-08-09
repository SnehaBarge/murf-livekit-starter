import logging
import re

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    tokenize,
    room_io,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from prompts import SYSTEM_PROMPT

try:
    from src.memory import get_farmer, initialize_database, save_farmer
except ModuleNotFoundError:
    from memory import get_farmer, initialize_database, save_farmer

logger = logging.getLogger("agent")

load_dotenv(".env.local")


class Assistant(Agent):
    def __init__(self) -> None:
        initialize_database()
        self._memory_consent_granted = False
        self._memory_consent_requested = False
        super().__init__(instructions=SYSTEM_PROMPT)

    @staticmethod
    def _caller_user_id(context: RunContext) -> str | None:
        try:
            linked_participant = context.session.room_io.linked_participant
        except RuntimeError:
            return None

        if linked_participant is None:
            return None

        return linked_participant.identity

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        user_text = (new_message.text_content or "").strip().lower()
        normalized_text = re.sub(r"[^a-z0-9']+", " ", user_text).strip()
        assistant_messages = [
            message
            for message in turn_ctx.messages()
            if message.role == "assistant"
        ]
        latest_assistant_text = (
            assistant_messages[-1].text_content.lower()
            if assistant_messages and assistant_messages[-1].text_content
            else ""
        )
        permission_requested = (
            ("remember" in latest_assistant_text or "save" in latest_assistant_text)
            and "?" in latest_assistant_text
        )
        negative_consent = (
            normalized_text in {"no", "no thanks", "no thank you"}
            or normalized_text.startswith("no ")
            or any(
                phrase in normalized_text
                for phrase in (
                    "don't save",
                    "do not save",
                    "dont save",
                    "don't store",
                    "do not store",
                    "dont store",
                    "don't remember",
                    "do not remember",
                    "dont remember",
                    "don't keep",
                    "do not keep",
                    "dont keep",
                    "not save",
                    "not remember",
                )
            )
        )

        affirmative_consent = normalized_text in {
            "yes",
            "yeah",
            "yep",
            "sure",
            "okay",
            "ok",
            "please do",
            "go ahead",
            "i agree",
            "that is fine",
            "that's fine",
        } or normalized_text.startswith(
            (
                "yes ",
                "yeah ",
                "yep ",
                "sure ",
                "okay ",
                "ok ",
                "please do ",
                "go ahead ",
                "i agree ",
            )
        )

        if negative_consent:
            self._memory_consent_granted = False
            self._memory_consent_requested = False
        elif (self._memory_consent_requested or permission_requested) and affirmative_consent:
            self._memory_consent_granted = True
            self._memory_consent_requested = False
        else:
            self._memory_consent_requested = permission_requested

        await super().on_user_turn_completed(turn_ctx, new_message)

    @function_tool
    async def lookup_farmer(self, context: RunContext) -> str:
        """Look up the current caller's saved Krishi-Vani profile at the start of a conversation.

        Use this before greeting the caller so you can recognize returning farmers
        and naturally use relevant saved facts. The caller's LiveKit identity is
        used automatically; never ask the caller for a user ID. If no profile is
        found, continue as a normal first-time conversation.
        """
        user_id = self._caller_user_id(context)
        if user_id is None:
            return "No caller profile is available for this conversation."

        farmer = get_farmer(user_id)
        if farmer is None:
            return "No saved farmer profile was found for this caller."

        return (
            "Saved farmer profile found: "
            f"name={farmer['name']}; "
            f"language preference={farmer['language_preference'] or 'not provided'}; "
            f"crops={farmer['crops_grown'] or 'not provided'}; "
            f"land size={farmer['land_size'] or 'not provided'}; "
            f"district={farmer['district'] or 'not provided'}; "
            f"irrigation type={farmer['irrigation_type'] or 'not provided'}; "
            f"last interaction={farmer['last_interaction']}."
        )

    @function_tool
    async def save_farmer(
        self,
        context: RunContext,
        name: str,
        language_preference: str | None = None,
        crops_grown: str | None = None,
        land_size: str | None = None,
        district: str | None = None,
        irrigation_type: str | None = None,
    ) -> str:
        """Save or update the current caller's Krishi-Vani farmer profile.

        Use this only after the farmer has explicitly agreed to Krishi-Vani
        remembering or saving their information. Save the name and any Farm &
        Field facts the farmer has shared, including language preference, crops,
        land size, district, and irrigation type. The caller's LiveKit identity
        is used automatically; never ask for or expose a user ID or database
        details. If the farmer has not clearly said yes after being asked for
        permission, do not call this tool.
        """
        if not self._memory_consent_granted:
            return "I will not save your information unless you explicitly agree."

        user_id = self._caller_user_id(context)
        if user_id is None:
            return "I could not save your information because your caller identity is unavailable."

        save_farmer(
            user_id=user_id,
            name=name,
            language_preference=language_preference,
            crops_grown=crops_grown,
            land_size=land_size,
            district=district,
            irrigation_type=irrigation_type,
        )
        return "The farmer profile was saved for future conversations."


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Set up a voice AI pipeline using Murf Falcon, Gemini, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
        # See all available models at https://docs.livekit.io/agents/models/stt/
        stt=deepgram.STT(model="nova-3",language="multi",),
        # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
        # See all available models at https://docs.livekit.io/agents/models/llm/
        llm=google.LLM(
                model="gemini-3.5-flash-lite",
            ),
        # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
        # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
        tts=murf.TTS(
            voice="Anisha",style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
        # See more at https://docs.livekit.io/agents/build/turns
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        # allow the LLM to generate a response while waiting for the end of turn
        # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
        preemptive_generation=True,
    )

    # To use a realtime model instead of a voice pipeline, use the following session setup instead.
    # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
    # 1. Install livekit-agents[openai]
    # 2. Set OPENAI_API_KEY in .env.local
    # 3. Add `from livekit.plugins import openai` to the top of this file
    # 4. Use the following session setup instead of the version above
    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(voice="marin")
    # )

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    # Join the room and connect to the user
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
