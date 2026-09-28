"""Which API an agent's model runs on.

Claude models use the normal Claude Code login. DeepSeek models run through DeepSeek's
Anthropic-compatible endpoint, so the bundled claude CLI works unchanged: only the base URL,
the key and the model names differ. Costs the SDK reports are priced as Claude, so they are
wrong for DeepSeek; check the DeepSeek dashboard for real spend.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
KEY_NAMES = ("DEEPSEEK_API_KEY", "DEEPSEEK_API")
OPENAI_KEY_NAME = "OPENAI_API_KEY"
# the CLI names a small model for background work; keep it on the same DeepSeek model
SMALL_MODEL_VARS = ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL")


def is_deepseek(model: str) -> bool:
    return model.startswith("deepseek")


def is_openai(model: str) -> bool:
    return model.startswith(("gpt-", "o1", "o3", "o4"))


def deepseek_key(repo: Path, environ: Mapping[str, str] = os.environ) -> str:
    """The DeepSeek key from the environment, then the repo's .env (same names as the chat bot)."""
    for name in KEY_NAMES:
        if environ.get(name):
            return environ[name]
    env_file = repo / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() in KEY_NAMES and value.strip().strip("'\""):
                return value.strip().strip("'\"")
    raise SystemExit(f"DeepSeek model chosen but {KEY_NAMES[0]} is not set in the environment or {env_file}")


def openai_key(repo: Path, environ: Mapping[str, str] = os.environ) -> str:
    """Read the OpenAI key without ever including its value in errors or logs."""
    if environ.get(OPENAI_KEY_NAME):
        return environ[OPENAI_KEY_NAME]
    env_file = repo / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            value = value.strip().strip("'\"")
            if separator and name.strip() == OPENAI_KEY_NAME and value:
                return value
    raise SystemExit(f"GPT-6 mode chosen but {OPENAI_KEY_NAME} is not set in the environment or {env_file}")


def env_for(model: str, key: str) -> dict[str, str]:
    """Environment overrides for the claude CLI running this model; empty for Claude models."""
    if not is_deepseek(model):
        return {}
    return {
        "ANTHROPIC_BASE_URL": DEEPSEEK_BASE_URL,
        "ANTHROPIC_API_KEY": key,
        "ANTHROPIC_AUTH_TOKEN": "",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        **{name: model for name in SMALL_MODEL_VARS},
    }
