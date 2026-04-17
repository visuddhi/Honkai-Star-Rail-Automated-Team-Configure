from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

NAME_FIELDS = (
    "id",
    "key",
    "name",
    "characterId",
    "characterName",
    "avatarName",
    "displayName",
)

ROSTER_FIELDS = ("characters", "roster", "avatars", "units")


def slugify(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).lower())


def _normalize_fraction(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    if number <= 1:
        return max(0.0, min(number, 1.0))
    if number <= 10:
        return max(0.0, min(number / 10.0, 1.0))
    if number <= 100:
        return max(0.0, min(number / 100.0, 1.0))
    return default


def _trace_fraction(entry: dict[str, Any]) -> float:
    if "traceScore" in entry:
        return _normalize_fraction(entry.get("traceScore"), 0.72)

    traces = entry.get("traces") or entry.get("skills")
    if isinstance(traces, dict):
        values = []
        for raw in traces.values():
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
        if values:
            return max(0.0, min(sum(values) / (len(values) * 10.0), 1.0))

    if isinstance(traces, list):
        values = []
        for raw in traces:
            if isinstance(raw, dict):
                raw = raw.get("level")
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
        if values:
            return max(0.0, min(sum(values) / (len(values) * 10.0), 1.0))

    return 0.72


def _light_cone_fraction(entry: dict[str, Any]) -> float:
    if entry.get("signature") is True:
        return 0.95
    for field in ("lightConeTier", "lightConeScore", "weaponScore", "coneScore"):
        if field in entry:
            return _normalize_fraction(entry.get(field), 0.7)
    light_cone = entry.get("lightCone")
    if isinstance(light_cone, dict):
        if light_cone.get("signature") is True:
            return 0.95
        for field in ("score", "rank", "superimpose"):
            if field in light_cone:
                return _normalize_fraction(light_cone.get(field), 0.7)
    return 0.7


def _investment_score(entry: dict[str, Any]) -> float:
    level = entry.get("level", 80)
    try:
        level_fraction = max(0.0, min(float(level) / 80.0, 1.0))
    except (TypeError, ValueError):
        level_fraction = 0.9

    eidolon = entry.get("eidolon", entry.get("e", 0))
    try:
        eidolon_fraction = max(0.0, min(float(eidolon) / 6.0, 1.0))
    except (TypeError, ValueError):
        eidolon_fraction = 0.0

    relic_fraction = _normalize_fraction(
        entry.get("relicScore", entry.get("buildScore", entry.get("score"))),
        0.76,
    )
    trace_fraction = _trace_fraction(entry)
    light_cone_fraction = _light_cone_fraction(entry)

    score = (
        level_fraction * 34
        + eidolon_fraction * 16
        + relic_fraction * 22
        + trace_fraction * 18
        + light_cone_fraction * 10
    )
    return round(score, 1)


def _extract_roster_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for field in ROSTER_FIELDS:
            if isinstance(payload.get(field), list):
                return [item for item in payload[field] if isinstance(item, dict)]
    return []


def _extract_name(entry: dict[str, Any]) -> str | None:
    for field in NAME_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@lru_cache(maxsize=1)
def load_characters() -> list[dict[str, Any]]:
    with (DATA_DIR / "characters.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_scenarios() -> list[dict[str, Any]]:
    with (DATA_DIR / "scenarios.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def list_scenarios() -> list[dict[str, Any]]:
    return load_scenarios()


def get_scenario(scenario_id: str) -> dict[str, Any]:
    for scenario in load_scenarios():
        if scenario["id"] == scenario_id:
            return scenario
    raise KeyError(scenario_id)


@lru_cache(maxsize=1)
def load_sample_roster() -> dict[str, Any]:
    with (DATA_DIR / "sample_roster.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def character_index() -> dict[str, dict[str, Any]]:
    return {character["id"]: character for character in load_characters()}


@lru_cache(maxsize=1)
def alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for character in load_characters():
        aliases = [character["id"], character["name"], *character.get("aliases", [])]
        for alias in aliases:
            index[slugify(alias)] = character["id"]
    return index


def parse_roster_payload(roster_payload: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if isinstance(roster_payload, str):
        try:
            payload = json.loads(roster_payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"盒子 JSON 解析失败：{exc.msg}") from exc
    else:
        payload = roster_payload

    roster_list = _extract_roster_list(payload)
    if not roster_list:
        raise ValueError("未在输入中找到角色列表，请使用 characters / roster / avatars 等字段。")

    aliases = alias_index()
    characters = character_index()
    normalized: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen_ids: set[str] = set()

    for entry in roster_list:
        if entry.get("owned") is False:
            continue
        raw_name = _extract_name(entry)
        if not raw_name:
            skipped.append("有一条记录缺少角色名")
            continue
        character_id = aliases.get(slugify(raw_name))
        if not character_id:
            skipped.append(f"未识别角色：{raw_name}")
            continue
        if character_id in seen_ids:
            continue

        base = characters[character_id]
        normalized.append(
            {
                "id": character_id,
                "name": base["name"],
                "investment": _investment_score(entry),
                "base": base,
                "raw": entry,
            }
        )
        seen_ids.add(character_id)

    return normalized, skipped
