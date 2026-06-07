import asyncio

from src.chatbot.bilibili_url_extract import (
    extract_bilibili_url_from_text,
    normalize_bilibili_url,
    normalize_video_id_to_url,
    resolve_bilibili_video_url,
)


def test_normalize_video_id_to_url():
    assert normalize_video_id_to_url("BV1xx411c7mD") == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_extract_url_from_card_text():
    text = '{"desc":"demo","url":"https://b23.tv/abc123"}'

    assert extract_bilibili_url_from_text(text) == "https://b23.tv/abc123"


def test_normalize_dynamic_url():
    url = normalize_bilibili_url("https://t.bilibili.com/1234567890?spm_id_from=333.999.0.0")

    assert url == "https://t.bilibili.com/1234567890"


def test_resolve_plain_video_url_without_network():
    resolved = asyncio.run(resolve_bilibili_video_url("https://www.bilibili.com/video/BV1xx411c7mD"))

    assert resolved.url == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert resolved.kind == "video"
