import asyncio
import os
import sys
import warnings
from dotenv import load_dotenv

# Suppress the "non-text parts" warning
warnings.filterwarnings("ignore", message=".*non-text parts in the response.*")

# Add parent directory to path to import api modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402
from agents.factory import create_orchestrator, get_agent_context  # noqa: E402


async def _run_query(runner: Runner, query: str) -> str:
    msg = types.Content(role="user", parts=[types.Part(text=query)])
    full_response = ""
    async for event in runner.run_async(
        user_id="test", session_id="test", new_message=msg
    ):
        if event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    full_response += part.text
    return full_response


async def test_chat() -> None:
    load_dotenv(dotenv_path="../.env")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv(
        "GOOGLE_CLOUD_PROJECT", "random-poc-479104"
    )
    os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("GEMINI_REGION", "us-central1")
    invite_code = os.getenv("MASTER_INVITE_CODE", "test-code")
    orchestrator = create_orchestrator(invite_code)
    assert orchestrator.name == "aanya"
    runner = Runner(
        app_name="VeoGenTest",
        agent=orchestrator,
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )
    assert runner.app_name == "VeoGenTest"
    for query in [
        "Hi, who are you?",
        "I want to make a promo. What videos do I have?",
    ]:
        try:
            await _run_query(runner, query)
            assert isinstance(get_agent_context(), dict)
        except Exception as e:
            assert str(e) != ""


if __name__ == "__main__":
    asyncio.run(test_chat())
