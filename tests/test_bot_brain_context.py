from src.chatbot.bot_brain.context import build_context
from src.chatbot.bot_brain.observation import normalize_observation
from src.chatbot.bot_brain.types import BrainMemory


def test_context_marks_retrieved_memory():
    observation = normalize_observation("告诉我这个项目是干嘛的", scope="demo")
    bundle = build_context(
        observation,
        (
            BrainMemory(scope="demo", topic="about", content="public-safe bot base"),
        ),
    )

    assert "retrieved_demo_memory" in bundle.notes
