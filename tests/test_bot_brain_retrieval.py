from src.chatbot.bot_brain.local_store import LocalFactStore
from src.chatbot.bot_brain.observation import normalize_observation
from src.chatbot.bot_brain.retrieval import retrieve_memories
from src.chatbot.bot_brain.types import BrainMemory


def test_retrieval_prefers_matching_memory():
    store = LocalFactStore()
    store.add(BrainMemory(scope="demo", topic="bilibili", content="video file upload", tags=("bilibili",)))
    store.add(BrainMemory(scope="demo", topic="sign", content="daily check-in", tags=("sign",)))

    memories = retrieve_memories(store, normalize_observation("bilibili 怎么发视频", scope="demo"))

    assert memories
    assert memories[0].topic == "bilibili"
