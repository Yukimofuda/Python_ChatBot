from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

import nonebot


@dataclass(frozen=True)
class AdapterSpec:
    package: str
    class_name: str = "Adapter"


ADAPTERS: dict[str, AdapterSpec] = {
    "OneBot V11": AdapterSpec("nonebot.adapters.onebot.v11"),
    "OneBot V12": AdapterSpec("nonebot.adapters.onebot.v12"),
    "Telegram": AdapterSpec("nonebot.adapters.telegram"),
    "Discord": AdapterSpec("nonebot.adapters.discord"),
    "Feishu": AdapterSpec("nonebot.adapters.feishu"),
    "QQ": AdapterSpec("nonebot.adapters.qq"),
    "GitHub": AdapterSpec("nonebot.adapters.github"),
}


def register_optional_adapters() -> None:
    """Register every supported adapter that is installed in this environment."""
    driver = nonebot.get_driver()
    logger = logging.getLogger("chatbot.adapters")

    for platform, spec in ADAPTERS.items():
        try:
            module = importlib.import_module(spec.package)
            adapter = getattr(module, spec.class_name)
        except (ImportError, AttributeError) as exc:
            logger.debug("Skip %s adapter: %s", platform, exc)
            continue

        driver.register_adapter(adapter)
        logger.info("Registered %s adapter", platform)


nonebot.init()
register_optional_adapters()
nonebot.load_from_toml("pyproject.toml")

app = nonebot.get_asgi()

if __name__ == "__main__":
    nonebot.run()
