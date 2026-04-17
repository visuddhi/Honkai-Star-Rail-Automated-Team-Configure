from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any

from src.data_loader import parse_roster_payload
from src.simulator import attach_simulations

TRAIT_LABELS = {
    "aoe": "对群",
    "single": "对单",
    "break": "击破",
    "debuff": "减益",
    "dot": "持续伤害",
    "fua": "追击",
    "speed": "节奏",
    "survival": "生存",
    "support": "辅助链",
}

TRAIT_REASON = {
    "aoe": "对群覆盖足够，适合当前多波次压力",
    "single": "单体爆发强，能更稳压低 Boss 斩杀线",
    "break": "削韧与击破节奏优秀，能吃到机制收益",
    "debuff": "减益覆盖完整，适配当前对负面状态的需求",
    "dot": "持续伤害链条完整，能稳定处理多目标战斗",
    "fua": "追击频率高，适合需要快速滚雪球的环境",
    "speed": "行动节奏快，容错和轮次表现都更稳",
    "survival": "生存面完整，不容易因为高压环境掉星",
    "support": "辅助链完整，主核输出更容易拉满",
}

ROLE_FAMILY = {
    "main_dps": "damage",
    "sub_dps": "damage",
    "support": "support",
    "sustain": "sustain",
}


class RecommendationError(ValueError):
    pass


def _effective_traits(unit: dict[str, Any]) -> dict[str, float]:
    multiplier = 0.78 + (unit["investment"] / 100.0) * 0.42
    traits: dict[str, float] = {}
    for key, value in unit["base"]["traits"].items():
        traits[key] = float(round(value * multiplier, 2))

    build = unit.get("build") or {}
    roles = set(unit["base"]["roles"])
    tags = set(unit["base"].get("tags", []))
    detail = 0.45 + float(build.get("detailLevel", 0.0)) * 0.55

    speed_bonus = build.get("speed", 0.0) * 3.0 + build.get("energy", 0.0) * 0.8
    break_bonus = build.get("break", 0.0) * (4.0 if {"break", "super_break"} & tags else 1.7)
    dot_bonus = build.get("dot", 0.0) * (3.8 if "dot" in tags else 1.2)
    fua_bonus = build.get("fua", 0.0) * (3.6 if "fua" in tags else 1.1)
    debuff_bonus = build.get("debuff", 0.0) * (3.2 if "nihility" in tags or traits.get("debuff", 0.0) >= 5 else 1.3)
    support_bonus = build.get("support", 0.0) * (3.2 if "support" in roles else 1.0) + build.get("energy", 0.0) * (
        1.8 if {"support", "sustain"} & roles else 0.7
    )
    survival_bonus = build.get("heal", 0.0) * (3.7 if "sustain" in roles else 1.2) + build.get("survival", 0.0) * (
        2.0 if "sustain" in roles else 0.9
    )
    damage_bonus = build.get("damage", 0.0)
    crit_bonus = build.get("crit", 0.0)

    traits["speed"] += speed_bonus * detail
    traits["break"] += break_bonus * detail
    traits["dot"] += dot_bonus * detail
    traits["fua"] += fua_bonus * detail
    traits["debuff"] += debuff_bonus * detail
    traits["support"] += support_bonus * detail
    traits["survival"] += survival_bonus * detail

    if "dot" in tags:
        traits["aoe"] += (damage_bonus * 0.9 + build.get("dot", 0.0) * 1.2) * 2.2 * detail
        traits["single"] += (damage_bonus * 0.7 + build.get("dot", 0.0) * 0.8) * 1.5 * detail
    elif "fua" in tags:
        traits["aoe"] += (crit_bonus * 1.0 + damage_bonus * 0.6) * 1.9 * detail
        traits["single"] += (crit_bonus * 1.2 + damage_bonus * 0.9) * 1.8 * detail
        traits["fua"] += crit_bonus * 1.1 * detail
    elif {"break", "super_break"} & tags:
        traits["single"] += (crit_bonus * 0.3 + damage_bonus * 0.7 + build.get("break", 0.0) * 1.1) * 2.0 * detail
        traits["aoe"] += (damage_bonus * 0.5 + build.get("break", 0.0) * 0.8) * 1.6 * detail
    else:
        single_scale = 2.3 if "main_dps" in roles else 1.2
        aoe_scale = 1.8 if "main_dps" in roles else 0.9
        traits["single"] += (crit_bonus * 1.15 + damage_bonus) * single_scale * detail
        traits["aoe"] += (crit_bonus * 0.8 + damage_bonus) * aoe_scale * detail

    for key in traits:
        traits[key] = round(traits[key], 2)
    return traits


def _role_counts(team: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for unit in team:
        for role in unit["base"]["roles"]:
            counts[role] += 1
    return counts


def _team_traits(team: list[dict[str, Any]]) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for unit in team:
        totals.update(unit["effective_traits"])
    return {key: round(value, 2) for key, value in totals.items()}


def _element_bonus(team: list[dict[str, Any]], half: dict[str, Any]) -> tuple[float, str | None]:
    preferred = set(half.get("preferredElements", []))
    elements = {unit["base"]["element"] for unit in team}
    matches = sorted(preferred & elements)
    if not preferred:
        return 0.0, None
    if not matches:
        return -2.5, "元素命中较少，更多依赖硬练度与机制对冲"

    bonus = min(len(matches), 2) * 2.4
    reason = f"命中推荐弱点元素：{' / '.join(matches)}"
    return bonus, reason


def _synergy_bonus(team: list[dict[str, Any]]) -> tuple[float, list[str]]:
    team_ids = {unit["id"] for unit in team}
    seen_pairs: set[tuple[str, str]] = set()
    raw_score = 0.0
    reasons: list[str] = []

    for unit in team:
        for link in unit["base"].get("synergies", []):
            target = link["with"]
            if target not in team_ids:
                continue
            pair = tuple(sorted((unit["id"], target)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            raw_score += float(link["score"])
            if len(reasons) < 2:
                reasons.append(link["reason"])

    return round(min(raw_score * 0.72, 12.0), 2), reasons


def _composition_bonus(team: list[dict[str, Any]], half: dict[str, Any], mode: str, traits: dict[str, float]) -> tuple[float, list[str]]:
    roles = _role_counts(team)
    damage = roles["main_dps"] + roles["sub_dps"]
    sustain = roles["sustain"]
    support = roles["support"]
    score = 0.0
    reasons: list[str] = []

    if mode == "pure_fiction":
        if sustain == 0:
            score += 4.5
            reasons.append("虚构环境里压低生存位占比，把资源更多给到清杂效率")
        elif sustain == 1:
            score += 2.0
        if traits.get("aoe", 0) >= half["targets"].get("aoe", 16) * 0.9:
            score += 3.0
        if traits.get("fua", 0) >= half["targets"].get("fua", 10) * 0.8 or traits.get("dot", 0) >= half["targets"].get("dot", 10) * 0.8:
            score += 2.5
    else:
        if sustain == 1:
            score += 5.0
            reasons.append("单生存成型，兼顾容错和输出位密度")
        elif sustain == 2:
            score += 1.0
        else:
            score -= 6.0
        if damage >= 1 and support >= 2:
            score += 4.0
            reasons.append("主核 + 双辅助结构完整，爆发更稳定")
        elif damage >= 2 and support >= 1:
            score += 2.5
        if damage >= 3:
            score -= 2.5
            reasons.append("输出位偏多，更依赖练度和手操来弥补功能位不足")

    return round(score, 2), reasons[:2]


def _team_sp_score(team: list[dict[str, Any]]) -> float:
    return round(sum(unit["base"]["traits"].get("sp", 0) for unit in team), 2)


def _is_team_valid(team: list[dict[str, Any]], half: dict[str, Any], mode: str) -> bool:
    roles = _role_counts(team)
    damage = roles["main_dps"] + roles["sub_dps"]
    sustain = roles["sustain"]
    support = roles["support"]
    traits = _team_traits(team)
    sp_score = _team_sp_score(team)

    if damage < 1:
        return False
    if sustain > 2:
        return False
    if support == 0 and damage < 2:
        return False
    if mode != "pure_fiction" and support == 0:
        return False
    if support + sustain < 2:
        return False
    if sp_score < -2.2:
        return False
    if mode != "pure_fiction" and half.get("requireSustain", False):
        if sustain == 0 and traits.get("survival", 0) < half["targets"].get("survival", 10) * 0.92:
            return False
    if mode == "pure_fiction" and sustain > 1:
        return False
    return True


def _trait_breakdown(traits: dict[str, float], half: dict[str, Any]) -> tuple[float, list[dict[str, float]]]:
    total = 0.0
    breakdown: list[dict[str, float]] = []
    for trait, weight in half["weights"].items():
        supply = traits.get(trait, 0.0)
        target = max(float(half["targets"].get(trait, 1.0)), 1.0)
        ratio = min(supply / target, 1.0)
        points = round(weight * ratio, 2)
        total += points
        breakdown.append(
            {
                "trait": trait,
                "supply": round(supply, 2),
                "target": target,
                "ratio": round(ratio, 2),
                "points": points,
            }
        )
    breakdown.sort(key=lambda item: item["points"], reverse=True)
    return round(total, 2), breakdown


def _unit_fit_scores(team: list[dict[str, Any]], half: dict[str, Any]) -> list[tuple[dict[str, Any], float]]:
    scored: list[tuple[dict[str, Any], float]] = []
    for unit in team:
        fit = 0.0
        for trait, weight in half["weights"].items():
            target = max(float(half["targets"].get(trait, 1.0)), 1.0)
            contribution = unit["effective_traits"].get(trait, 0.0)
            fit += min(contribution / target, 1.0) * weight
        scored.append((unit, round(fit, 2)))
    return scored


def _key_units(team: list[dict[str, Any]], half: dict[str, Any]) -> list[str]:
    weighted_units: list[tuple[float, str]] = []
    for unit, score in _unit_fit_scores(team, half):
        score += unit["investment"] / 20.0
        synergy_links = sum(link["score"] for link in unit["base"].get("synergies", []) if any(other["id"] == link["with"] for other in team))
        score += synergy_links * 0.25
        weighted_units.append((score, unit["name"]))
    weighted_units.sort(reverse=True)
    return [name for _, name in weighted_units[:2]]


def _score_team(team: list[dict[str, Any]], half: dict[str, Any], mode: str) -> dict[str, Any]:
    traits = _team_traits(team)
    trait_score, breakdown = _trait_breakdown(traits, half)
    synergy_score, synergy_reasons = _synergy_bonus(team)
    composition_score, composition_reasons = _composition_bonus(team, half, mode, traits)
    element_score, element_reason = _element_bonus(team, half)
    sp_score = _team_sp_score(team)
    investment_bonus = round((sum(unit["investment"] for unit in team) / len(team) - 74.0) * 0.12, 2)
    penalty = 0.0

    if mode == "pure_fiction" and _role_counts(team)["sustain"] == 1 and traits.get("aoe", 0) < half["targets"].get("aoe", 16) * 0.8:
        penalty += 1.5
    if sp_score < -0.5:
        penalty += abs(sp_score) * 1.2
    if traits.get("support", 0) < half["targets"].get("support", 0) * 0.65:
        penalty += 1.0
    if half["weights"].get("break", 0) >= 14 and traits.get("break", 0) < half["targets"].get("break", 12) * 0.85:
        penalty += 2.0
    for unit, fit_score in _unit_fit_scores(team, half):
        if "sustain" in unit["base"]["roles"]:
            continue
        if fit_score < 11.0:
            penalty += round((11.0 - fit_score) * 0.35, 2)

    total = round(min(100.0, trait_score + synergy_score + composition_score + element_score + investment_bonus - penalty), 1)

    reasons: list[str] = []
    for item in breakdown[:3]:
        if item["ratio"] >= 0.7:
            reasons.append(TRAIT_REASON[item["trait"]])
    reasons.extend(synergy_reasons)
    if element_reason:
        reasons.append(element_reason)
    reasons.extend(composition_reasons)

    deduped_reasons: list[str] = []
    for reason in reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)

    return {
        "score": total,
        "characters": [unit["name"] for unit in team],
        "characterIds": [unit["id"] for unit in team],
        "traits": traits,
        "breakdown": breakdown,
        "reasons": deduped_reasons[:5],
        "spScore": sp_score,
        "keyUnits": _key_units(team, half),
    }


def _pair_summary(top_team: dict[str, Any], bottom_team: dict[str, Any], scenario: dict[str, Any]) -> str:
    mode_label = scenario["modeLabel"]
    if scenario["mode"] == "pure_fiction":
        return f"{mode_label}里这套分工清晰：上半优先控多目标节奏，下半继续放大清杂和滚雪球能力。"
    if scenario["mode"] == "apocalyptic_shadow":
        return f"{mode_label}里这套组合把削韧和单体爆发拆开处理，两边都更接近稳定拿满奖励的思路。"
    return f"{mode_label}里这套双队把上半环境需求与下半 Boss 压力拆开处理，角色资源没有互相挤占。"


def _score_label(score: float) -> str:
    if score >= 90:
        return "稳满星候选"
    if score >= 84:
        return "高优先级"
    if score >= 76:
        return "可用备选"
    return "勉强可打"


def _pair_candidates(
    top_candidates: list[dict[str, Any]],
    bottom_candidates: list[dict[str, Any]],
    roster_units: list[dict[str, Any]],
    top_half: dict[str, Any],
    bottom_half: dict[str, Any],
    scenario: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    id_to_bit = {unit["id"]: 1 << index for index, unit in enumerate(roster_units)}
    exact_pair_limit = 1_200_000
    approximate_pool = 40
    exact_pairing = len(top_candidates) * len(bottom_candidates) <= exact_pair_limit

    search_top = top_candidates if exact_pairing else top_candidates[:approximate_pool]
    search_bottom = bottom_candidates if exact_pairing else bottom_candidates[:approximate_pool]
    top_masks = [sum(id_to_bit[unit_id] for unit_id in team["characterIds"]) for team in search_top]
    bottom_masks = [sum(id_to_bit[unit_id] for unit_id in team["characterIds"]) for team in search_bottom]

    paired_results: list[dict[str, Any]] = []
    for top_team, top_mask in zip(search_top, top_masks):
        for bottom_team, bottom_mask in zip(search_bottom, bottom_masks):
            if top_mask & bottom_mask:
                continue
            balance_bonus = round(max(0.0, 3.0 - abs(top_team["score"] - bottom_team["score"]) / 8.0), 2)
            total_score = round(min(100.0, (top_team["score"] + bottom_team["score"]) / 2.0 + balance_bonus), 1)
            paired_results.append(
                {
                    "score": total_score,
                    "scoreLabel": _score_label(total_score),
                    "teams": [
                        {**top_team, "half": top_half["name"]},
                        {**bottom_team, "half": bottom_half["name"]},
                    ],
                    "summary": _pair_summary(top_team, bottom_team, scenario),
                }
            )

    paired_results.sort(key=lambda item: item["score"], reverse=True)
    return (
        paired_results,
        {
            "singleTeam": "穷举所有 4 人组合",
            "pairing": "全量候选精确配对" if exact_pairing else f"Top {approximate_pool} x Top {approximate_pool} 的近似配对",
            "pairingIsApproximate": not exact_pairing,
            "pairedTopCandidates": len(search_top),
            "pairedBottomCandidates": len(search_bottom),
        },
    )


def _replacement_score(candidate: dict[str, Any], missing: dict[str, Any], half: dict[str, Any]) -> float:
    score = 0.0
    family_a = {ROLE_FAMILY.get(role, role) for role in candidate["base"]["roles"]}
    family_b = {ROLE_FAMILY.get(role, role) for role in missing["base"]["roles"]}
    if family_a & family_b:
        score += 5.0
    shared_tags = set(candidate["base"].get("tags", [])) & set(missing["base"].get("tags", []))
    score += len(shared_tags) * 1.5
    if candidate["base"]["element"] == missing["base"]["element"]:
        score += 1.0
    for trait, weight in half["weights"].items():
        diff = abs(candidate["effective_traits"].get(trait, 0.0) - missing["effective_traits"].get(trait, 0.0))
        score += max(0.0, weight / 10.0 - diff / 8.0)
    return round(score, 2)


def _build_substitutions(
    selected_team: list[dict[str, Any]],
    other_team_ids: set[str],
    roster_units: list[dict[str, Any]],
    half: dict[str, Any],
    mode: str,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    pool = [unit for unit in roster_units if unit["id"] not in other_team_ids]
    scored_team = _score_team(selected_team, half, mode)
    key_names = set(scored_team["keyUnits"])

    for missing in selected_team:
        if missing["name"] not in key_names:
            continue

        candidates = [unit for unit in pool if unit["id"] != missing["id"] and unit["id"] not in {member["id"] for member in selected_team}]
        ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for candidate in candidates:
            new_team = [candidate if member["id"] == missing["id"] else member for member in selected_team]
            if not _is_team_valid(new_team, half, mode):
                continue
            new_score = _score_team(new_team, half, mode)
            fit = _replacement_score(candidate, missing, half)
            ranked.append((fit + new_score["score"], candidate, new_score))

        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            continue

        best = []
        for _, candidate, new_score in ranked[:2]:
            delta = round(new_score["score"] - scored_team["score"], 1)
            best.append(
                {
                    "name": candidate["name"],
                    "newScore": new_score["score"],
                    "delta": delta,
                    "reason": "保留了相近的角色定位，并尽量补上当前半场最重的权重项。",
                }
            )

        suggestions.append(
            {
                "missing": missing["name"],
                "options": best,
            }
        )

    return suggestions


def _attach_runtime_fields(roster_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attached = []
    for unit in roster_units:
        attached.append({**unit, "effective_traits": _effective_traits(unit)})
    return attached


def build_recommendation(scenario: dict[str, Any], roster_payload: Any) -> dict[str, Any]:
    try:
        roster_units, skipped = parse_roster_payload(roster_payload)
    except ValueError as exc:
        raise RecommendationError(str(exc)) from exc

    if len(roster_units) < 8:
        raise RecommendationError("当前盒子可识别角色少于 8 名，无法组成有效双队。")

    roster_units = _attach_runtime_fields(roster_units)
    mode = scenario["mode"]
    top_half, bottom_half = scenario["halves"]
    all_combos = list(combinations(roster_units, 4))
    detailed_relic_units = sum(1 for unit in roster_units if unit.get("build", {}).get("hasDetailedRelics"))
    parsed_relic_detail_units = sum(1 for unit in roster_units if unit.get("build", {}).get("detailLevel", 0.0) > 0.2)

    top_candidates: list[dict[str, Any]] = []
    bottom_candidates: list[dict[str, Any]] = []

    for combo in all_combos:
        team = list(combo)
        if _is_team_valid(team, top_half, mode):
            top_candidates.append(_score_team(team, top_half, mode))
        if _is_team_valid(team, bottom_half, mode):
            bottom_candidates.append(_score_team(team, bottom_half, mode))

    if not top_candidates or not bottom_candidates:
        raise RecommendationError("没有找到满足约束的队伍，请补充角色或放宽输入盒子。")

    top_candidates.sort(key=lambda item: item["score"], reverse=True)
    bottom_candidates.sort(key=lambda item: item["score"], reverse=True)
    paired_results, search_meta = _pair_candidates(top_candidates, bottom_candidates, roster_units, top_half, bottom_half, scenario)
    paired_results.sort(key=lambda item: item["score"], reverse=True)
    results = paired_results[:10]

    roster_by_id = {unit["id"]: unit for unit in roster_units}
    for result in results:
        top_ids = set(result["teams"][0]["characterIds"])
        bottom_ids = set(result["teams"][1]["characterIds"])
        top_team_units = [roster_by_id[unit_id] for unit_id in result["teams"][0]["characterIds"]]
        bottom_team_units = [roster_by_id[unit_id] for unit_id in result["teams"][1]["characterIds"]]
        result["alternatives"] = [
            {
                "half": top_half["name"],
                "suggestions": _build_substitutions(top_team_units, bottom_ids, roster_units, top_half, mode),
            },
            {
                "half": bottom_half["name"],
                "suggestions": _build_substitutions(bottom_team_units, top_ids, roster_units, bottom_half, mode),
            },
        ]

    simulation_meta = attach_simulations(scenario, results, roster_by_id)

    return {
        "scenario": {
            "id": scenario["id"],
            "name": scenario["name"],
            "mode": scenario["mode"],
            "modeLabel": scenario["modeLabel"],
            "description": scenario["description"],
            "buffs": scenario.get("buffs", []),
        },
        "meta": {
            "rosterSize": len(roster_units),
            "evaluatedTeams": len(all_combos),
            "topTeamCandidates": len(top_candidates),
            "bottomTeamCandidates": len(bottom_candidates),
            "detailedRelicUnits": detailed_relic_units,
            "parsedRelicDetailUnits": parsed_relic_detail_units,
            "search": search_meta,
            "skipped": skipped,
        },
        "simulationMeta": simulation_meta,
        "results": results,
    }
