"""Configuration: presets, env overrides, paths."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml


def _find_presets_dir() -> Path:
    """Locate the bundled presets directory.

    Checks (in order):
      1. Inside the installed package (site-packages/learnage/presets)
      2. Source-tree layout (../../presets relative to learnage/config.py)
    """
    pkg_local = Path(__file__).resolve().parent / "presets"
    if pkg_local.exists():
        return pkg_local
    src_tree = Path(__file__).resolve().parent.parent / "presets"
    if src_tree.exists():
        return src_tree
    # Fall back to whichever the caller expects — empty available list
    return pkg_local


PRESETS_DIR = _find_presets_dir()


@dataclass
class Preset:
    name: str = "balanced"
    description: str = ""
    llm: str = "qwen3:14b"
    embed: str = "nomic-embed-text"
    chunk_target_tokens: int = 800
    chunk_overlap_tokens: int = 150
    retrieval_k: int = 8
    soul_model: str = "qwen3:14b"
    soul_max_input_chars: int = 80_000
    extra: dict = field(default_factory=dict)

    def with_overrides(self, **kw) -> "Preset":
        """Return a copy with the given fields replaced."""
        valid = {f for f in self.__dataclass_fields__}
        updates = {k: v for k, v in kw.items() if k in valid and v is not None}
        return replace(self, **updates)


def load_preset(name: str) -> Preset:
    path = PRESETS_DIR / f"{name}.yaml"
    if not path.exists():
        available = ", ".join(p.stem for p in PRESETS_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"Unknown preset {name!r}. Available: {available}"
        )
    data = yaml.safe_load(path.read_text()) or {}
    data["name"] = name
    return Preset(**data)


def default_preset_name() -> str:
    return os.environ.get("LEARNAGE_PRESET", "balanced")
