from __future__ import annotations

import importlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def isolate_virtualenv_pythonpath() -> None:
    """Drop external PYTHONPATH entries before importing third-party packages."""
    project_root = Path(__file__).resolve().parent
    venv_root = Path(sys.prefix).resolve()
    pythonpath_entries = {
        str(Path(entry).expanduser().resolve())
        for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if entry
    }

    filtered_path: list[str] = []
    for entry in sys.path:
        if not entry:
            filtered_path.append(entry)
            continue

        resolved = Path(entry).expanduser().resolve()
        is_project_path = resolved == project_root or project_root in resolved.parents
        is_venv_path = resolved == venv_root or venv_root in resolved.parents
        is_injected_external_path = str(resolved) in pythonpath_entries and not (
            is_project_path or is_venv_path
        )

        if not is_injected_external_path:
            filtered_path.append(entry)

    sys.path[:] = filtered_path


isolate_virtualenv_pythonpath()

import nonebot  # noqa: E402

from src.chatbot.admin_web import setup_admin_routes  # noqa: E402
from src.chatbot.settings import get_settings  # noqa: E402


@dataclass(frozen=True)
class AdapterSpec:
    package: str
    class_name: str = "Adapter"


ADAPTERS: dict[str, AdapterSpec] = {
    "onebot_v11": AdapterSpec("nonebot.adapters.onebot.v11"),
    "onebot_v12": AdapterSpec("nonebot.adapters.onebot.v12"),
    "telegram": AdapterSpec("nonebot.adapters.telegram"),
    "discord": AdapterSpec("nonebot.adapters.discord"),
    "feishu": AdapterSpec("nonebot.adapters.feishu"),
    "qq": AdapterSpec("nonebot.adapters.qq"),
    "github": AdapterSpec("nonebot.adapters.github"),
}


def register_optional_adapters() -> None:
    """Register every supported adapter that is installed in this environment."""
    driver = nonebot.get_driver()
    logger = logging.getLogger("chatbot.adapters")
    enabled_adapters = get_settings().enabled_adapters

    for adapter_key, spec in ADAPTERS.items():
        if enabled_adapters and adapter_key not in enabled_adapters:
            logger.debug("Skip %s adapter: disabled by configuration", adapter_key)
            continue
        try:
            module = importlib.import_module(spec.package)
            adapter = getattr(module, spec.class_name)
        except (ImportError, AttributeError) as exc:
            logger.debug("Skip %s adapter: %s", adapter_key, exc)
            continue

        driver.register_adapter(adapter)
        logger.info("Registered %s adapter", adapter_key)


nonebot.init()
register_optional_adapters()
nonebot.load_from_toml("pyproject.toml")
setup_admin_routes(nonebot.get_app())

app = nonebot.get_asgi()

if __name__ == "__main__":
    nonebot.run()
