from src.chatbot.bilibili_url_extract import BilibiliCardInfo, build_preview_text


def test_preview_text_prioritizes_summary_and_url():
    preview = build_preview_text(
        BilibiliCardInfo(
            title="Demo title",
            desc="Demo description",
            raw_url="https://www.bilibili.com/video/BV1xx411c7mD",
            video_url="https://www.bilibili.com/video/BV1xx411c7mD",
        )
    )

    assert "Demo title" in preview
    assert "Demo description" in preview
    assert "https://www.bilibili.com/video/BV1xx411c7mD" in preview
