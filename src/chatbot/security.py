from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse


URL_RE = re.compile(r"https?://[^\s<>\"]+")


def extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text)


def extract_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def format_file_size(size: int | float | None) -> str:
    if size is None:
        return "未知大小"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def validate_text_length(text: str, max_len: int) -> str:
    clean = text.strip()
    if not clean:
        raise ValueError("内容不能为空")
    if len(clean) > max_len:
        raise ValueError(f"内容过长，最多 {max_len} 字")
    return clean


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", name).strip(" .")
    return cleaned[:80] or "file"


def is_safe_relative_path(path: str | Path) -> bool:
    candidate = Path(path)
    return not candidate.is_absolute() and ".." not in candidate.parts


def cleanup_temp_files(directory: str | Path, max_age_seconds: int) -> int:
    root = Path(directory).expanduser()
    if not root.exists() or not root.is_dir():
        return 0
    now = time.time()
    cleaned = 0
    for path in root.iterdir():
        if not path.is_file():
            continue
        try:
            if now - path.stat().st_mtime >= max_age_seconds:
                path.unlink()
                cleaned += 1
        except OSError:
            continue
    return cleaned
