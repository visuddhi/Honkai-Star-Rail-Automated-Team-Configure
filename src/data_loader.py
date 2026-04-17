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
RELIC_LIST_FIELDS = ("relics", "artifacts", "gear", "equipment", "equips", "items", "ornaments", "planarOrnaments")
STAT_OBJECT_FIELDS = ("stats", "attributes", "combatStats", "summaryStats")


def slugify(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).lower())


def _parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


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


def _stat_bucket(name: Any) -> str | None:
    slug = slugify(name)
    if not slug:
        return None
    if any(key in slug for key in ("speed", "spd", "速度")):
        return "speed"
    if any(key in slug for key in ("break", "击破", "破击")):
        return "break"
    if any(key in slug for key in ("critrate", "critrate", "暴击率")):
        return "crit_rate"
    if any(key in slug for key in ("critdmg", "critdamage", "暴击伤害", "暴伤")):
        return "crit_dmg"
    if any(key in slug for key in ("effecthit", "hitrate", "效果命中", "命中")):
        return "debuff"
    if any(key in slug for key in ("energyregen", "ener", "能量恢复", "充能")):
        return "energy"
    if any(key in slug for key in ("outgoinghealing", "healing", "heal", "治疗量")):
        return "heal"
    if any(key in slug for key in ("effectres", "抵抗")):
        return "survival"
    if any(key in slug for key in ("hp", "生命", "def", "防御")):
        return "survival"
    if any(key in slug for key in ("atk", "攻击", "damage", "dmg", "增伤")):
        return "damage"
    return None


def _normalize_stat_value(bucket: str, value: Any) -> float:
    number = _parse_number(value)
    if number is None:
        return 0.0
    scales = {
        "speed": 35.0,
        "break": 220.0,
        "crit_rate": 100.0,
        "crit_dmg": 220.0,
        "debuff": 120.0,
        "energy": 30.0,
        "heal": 50.0,
        "survival": 140.0,
        "damage": 120.0,
    }
    scale = scales.get(bucket, 100.0)
    return max(0.0, min(number / scale, 1.0))


def _extract_relic_entries(entry: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for field in RELIC_LIST_FIELDS:
        value = entry.get(field)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            for nested in ("items", "relics", "pieces", "ornaments"):
                nested_value = value.get(nested)
                if isinstance(nested_value, list):
                    items.extend(item for item in nested_value if isinstance(item, dict))
    return items


def _extract_stat_items(raw: Any) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            items.append((str(key), value))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                stat_name = item.get("type", item.get("name", item.get("stat", item.get("key"))))
                stat_value = item.get("value", item.get("amount", item.get("score", item.get("num"))))
                if stat_name is not None:
                    items.append((str(stat_name), stat_value))
    return items


def _set_bonus_bucket(set_name: str) -> dict[str, float]:
    slug = slugify(set_name)
    if not slug:
        return {}
    if any(key in slug for key in ("铁骑", "钟表", "盗贼", "meteor", "watchmaker", "thief")):
        return {"break": 0.2}
    if any(key in slug for key in ("囚", "prison", "prisoner", "dot")):
        return {"dot": 0.18, "debuff": 0.06}
    if any(key in slug for key in ("大公", "杜兰", "duran", "grandduke", "salsotto")):
        return {"fua": 0.18}
    if any(key in slug for key in ("信使", "messenger")):
        return {"speed": 0.16}
    if any(key in slug for key in ("龙骨", "brokenkeel", "仙舟", "fleet", "梦", "penacony")):
        return {"support": 0.14}
    if any(key in slug for key in ("过客", "healer", "wanderer")):
        return {"heal": 0.2, "support": 0.08}
    if any(key in slug for key in ("繁星", "死水", "猎人", "pioneer", "scholar", "musketeer")):
        return {"crit": 0.14, "damage": 0.08}
    return {}


def _derive_build_profile(entry: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    build = {
        "quality": 0.0,
        "speed": 0.0,
        "break": 0.0,
        "crit": 0.0,
        "dot": 0.0,
        "debuff": 0.0,
        "fua": 0.0,
        "support": 0.0,
        "heal": 0.0,
        "energy": 0.0,
        "survival": 0.0,
        "damage": 0.0,
        "detailLevel": 0.0,
        "pieces": 0,
        "sets": [],
        "hasDetailedRelics": False,
    }

    raw_strength = 0.0
    top_level_hits = 0
    for field in STAT_OBJECT_FIELDS:
        value = entry.get(field)
        for stat_name, stat_value in _extract_stat_items(value):
            bucket = _stat_bucket(stat_name)
            if not bucket:
                continue
            amount = _normalize_stat_value(bucket, stat_value)
            top_level_hits += 1
            raw_strength += amount
            if bucket == "crit_rate":
                build["crit"] += amount * 0.55
            elif bucket == "crit_dmg":
                build["crit"] += amount * 0.45
            else:
                build[bucket] = build.get(bucket, 0.0) + amount

    for field in ("speed", "spd", "breakEffect", "effectHitRate", "critRate", "critDamage", "energyRegen", "outgoingHealing"):
        if field not in entry:
            continue
        bucket = _stat_bucket(field)
        if not bucket:
            continue
        amount = _normalize_stat_value(bucket, entry.get(field))
        top_level_hits += 1
        raw_strength += amount
        if bucket == "crit_rate":
            build["crit"] += amount * 0.55
        elif bucket == "crit_dmg":
            build["crit"] += amount * 0.45
        else:
            build[bucket] = build.get(bucket, 0.0) + amount

    relic_items = _extract_relic_entries(entry)
    set_counts: dict[str, int] = {}
    piece_quality = 0.0
    for item in relic_items:
        build["hasDetailedRelics"] = True
        build["pieces"] += 1

        set_name = item.get("setName", item.get("set", item.get("relicSet")))
        if isinstance(set_name, str) and set_name.strip():
            key = set_name.strip()
            set_counts[key] = set_counts.get(key, 0) + 1

        level_fraction = max(0.0, min((_parse_number(item.get("level")) or 0.0) / 15.0, 1.0))
        rarity_fraction = max(0.0, min(((_parse_number(item.get("rarity")) or 4.0) - 3.0) / 2.0, 1.0))
        piece_quality += 0.08 + level_fraction * 0.08 + rarity_fraction * 0.04

        for stat_name, stat_value in _extract_stat_items(item.get("substats")):
            bucket = _stat_bucket(stat_name)
            if not bucket:
                continue
            amount = _normalize_stat_value(bucket, stat_value) * 0.45
            raw_strength += amount
            if bucket == "crit_rate":
                build["crit"] += amount * 0.55
            elif bucket == "crit_dmg":
                build["crit"] += amount * 0.45
            else:
                build[bucket] = build.get(bucket, 0.0) + amount

        main_stat_name = item.get("mainStat", item.get("mainAffix", item.get("main")))
        main_bucket = _stat_bucket(main_stat_name)
        if main_bucket:
            amount = 0.28 + _normalize_stat_value(main_bucket, item.get("mainValue", item.get("value", 1.0))) * 0.28
            raw_strength += amount
            if main_bucket == "crit_rate":
                build["crit"] += amount * 0.55
            elif main_bucket == "crit_dmg":
                build["crit"] += amount * 0.45
            else:
                build[main_bucket] = build.get(main_bucket, 0.0) + amount

    for set_name, count in set_counts.items():
        if count < 2:
            continue
        build["sets"].append({"name": set_name, "count": count})
        for bucket, value in _set_bonus_bucket(set_name).items():
            build[bucket] = build.get(bucket, 0.0) + value * (1.5 if count >= 4 else 1.0)

    build["detailLevel"] = min(1.0, top_level_hits * 0.08 + build["pieces"] * 0.12)
    build["quality"] = min(1.0, raw_strength * 0.32 + piece_quality)

    tags = set(base.get("tags", []))
    if "dot" in tags:
        build["dot"] += build["damage"] * 0.35
    if "fua" in tags:
        build["fua"] += build["crit"] * 0.25
    if "break" in tags or "super_break" in tags:
        build["break"] += build["damage"] * 0.18
    if "team_buff" in tags or "hypercarry" in tags:
        build["support"] += build["energy"] * 0.3

    for key in ("speed", "break", "crit", "dot", "debuff", "fua", "support", "heal", "energy", "survival", "damage"):
        build[key] = round(max(0.0, min(build.get(key, 0.0), 1.4)), 3)
    build["quality"] = round(build["quality"], 3)
    build["detailLevel"] = round(build["detailLevel"], 3)
    return build


def _investment_score(entry: dict[str, Any], build: dict[str, Any] | None = None) -> float:
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

    explicit_relic = entry.get("relicScore", entry.get("buildScore", entry.get("score")))
    if explicit_relic is not None:
        relic_fraction = _normalize_fraction(explicit_relic, 0.76)
    elif build and build.get("quality", 0.0) > 0:
        relic_fraction = max(0.52, min(0.96, 0.48 + float(build["quality"]) * 0.52))
    else:
        relic_fraction = 0.76
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
def load_simulation_profiles() -> dict[str, Any]:
    path = DATA_DIR / "simulation_profiles.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
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
        build = _derive_build_profile(entry, base)
        normalized.append(
            {
                "id": character_id,
                "name": base["name"],
                "investment": _investment_score(entry, build),
                "build": build,
                "base": base,
                "raw": entry,
            }
        )
        seen_ids.add(character_id)

    return normalized, skipped
