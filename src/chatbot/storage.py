from __future__ import annotations

import json
import logging
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from src.chatbot.settings import get_settings


JsonDict = dict[str, Any]
logger = logging.getLogger(__name__)


class JsonPluginStorage:
    """Small JSON key-value store for plugin state."""

    def __init__(
        self,
        plugin_name: str,
        *,
        default: JsonDict | Callable[[], JsonDict] | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        self.plugin_name = _safe_name(plugin_name)
        root = Path(data_dir or get_settings().data_dir).expanduser()
        self.path = root / "plugins" / f"{self.plugin_name}.json"
        self._default = default
        self._lock = RLock()

    def read(self) -> JsonDict:
        with self._lock:
            return self._read_unlocked()

    def write(self, data: JsonDict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
                text=True,
            )
            temp_path = Path(temp_name)
            try:
                with open(fd, "w", encoding="utf-8") as file:
                    json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)
                    file.write("\n")
                    file.flush()
                temp_path.replace(self.path)
            except Exception:
                logger.exception("Failed to write JSON storage: %s", self.path)
                temp_path.unlink(missing_ok=True)
                raise

    def get(self, key: str, default: Any = None) -> Any:
        return self.read().get(key, default)

    def has(self, key: str) -> bool:
        return key in self.read()

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self._read_unlocked()
            data[key] = value
            self.write(data)

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._read_unlocked()
            existed = key in data
            if existed:
                del data[key]
                self.write(data)
            return existed

    def list(self) -> list[str]:
        return sorted(self.read().keys())

    def update(self, mutator: Callable[[JsonDict], None]) -> JsonDict:
        with self._lock:
            data = self._read_unlocked()
            mutator(data)
            self.write(data)
            return data

    def _read_unlocked(self) -> JsonDict:
        if not self.path.exists():
            return self._default_data()
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            backup_path = self._backup_corrupted_file()
            logger.exception("JSON storage is corrupted: %s, backup: %s", self.path, backup_path)
            raise ValueError(f"JSON storage is corrupted: {self.path}") from exc
        except OSError as exc:
            logger.exception("Failed to read JSON storage: %s", self.path)
            raise ValueError(f"JSON storage cannot be read: {self.path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"JSON storage root must be an object: {self.path}")
        return data

    def _backup_corrupted_file(self) -> Path | None:
        if not self.path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = self.path.with_suffix(f".corrupt-{stamp}.json")
        try:
            shutil.copy2(self.path, backup_path)
            return backup_path
        except OSError:
            logger.exception("Failed to backup corrupted JSON storage: %s", self.path)
            return None

    def _default_data(self) -> JsonDict:
        if callable(self._default):
            data = self._default()
        elif self._default is None:
            data = {}
        else:
            data = dict(self._default)
        if not isinstance(data, dict):
            raise ValueError("Storage default must be a dict")
        return data


def _safe_name(name: str) -> str:
    normalized = name.strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("Plugin storage name must be a simple file name")
    if Path(normalized).name != normalized:
        raise ValueError("Plugin storage name must not contain path components")
    return normalized
