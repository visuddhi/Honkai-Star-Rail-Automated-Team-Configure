from __future__ import annotations

import random
from statistics import mean
from typing import Any

PROFILE_DEFINITIONS = (
    {
        "id": "standard",
        "label": "普通随机",
        "description": "P50 结果，代表一般手感。",
        "quantile": 0.5,
    },
    {
        "id": "worst_case",
        "label": "最差随机",
        "description": "P15 结果，偏保守，不是绝对最差。",
        "quantile": 0.15,
    },
    {
        "id": "best_case",
        "label": "最佳随机",
        "description": "P85 结果，偏乐观，不是绝对上限。",
        "quantile": 0.85,
    },
)

MODE_AV_LIMIT = {
    "memory_of_chaos": 2700.0,
    "pure_fiction": 2300.0,
    "apocalyptic_shadow": 2450.0,
}


def attach_simulations(
    scenario: dict[str, Any],
    results: list[dict[str, Any]],
    roster_by_id: dict[str, dict[str, Any]],
    *,
    limit: int = 3,
    runs: int = 24,
) -> dict[str, Any]:
    if not results:
        return {
            "simulatedResults": 0,
            "runsPerResult": 0,
            "engine": "turn_prototype_v1",
        }

    simulated = 0
    for index, result in enumerate(results[:limit]):
        result["simulation"] = _simulate_pair_result(
            scenario,
            result,
            roster_by_id,
            runs=runs,
            pair_seed=_stable_seed(scenario["id"], str(index), *result["teams"][0]["characterIds"], *result["teams"][1]["characterIds"]),
        )
        simulated += 1

    return {
        "simulatedResults": simulated,
        "runsPerResult": runs,
        "engine": "turn_prototype_v1",
    }


def _simulate_pair_result(
    scenario: dict[str, Any],
    result: dict[str, Any],
    roster_by_id: dict[str, dict[str, Any]],
    *,
    runs: int,
    pair_seed: int,
) -> dict[str, Any]:
    teams = []
    for team in result["teams"]:
        units = [roster_by_id[unit_id] for unit_id in team["characterIds"] if unit_id in roster_by_id]
        teams.append({"team": team, "units": units})

    outcomes: list[dict[str, Any]] = []
    for run_index in range(runs):
        rng = random.Random(pair_seed + run_index * 7919)
        halves = []
        for team_bundle, half in zip(teams, scenario["halves"]):
            halves.append(_simulate_half(team_bundle["units"], half, scenario["mode"], rng))

        both_cleared = all(half["cleared"] for half in halves)
        pair_score = round(
            (halves[0]["score"] + halves[1]["score"]) / 2.0
            + (6.0 if both_cleared else -10.0)
            - abs(halves[0]["score"] - halves[1]["score"]) / 10.0,
            1,
        )
        pair_cycles = round(max(half["cycleEquivalent"] for half in halves), 1)
        outcomes.append(
            {
                "pairScore": max(0.0, min(pair_score, 100.0)),
                "pairCycles": pair_cycles,
                "bothCleared": both_cleared,
                "halves": halves,
            }
        )

    outcomes.sort(key=lambda item: item["pairScore"])
    pair_clear_rate = mean(1.0 if item["bothCleared"] else 0.0 for item in outcomes)
    top_half_clear_rate = mean(1.0 if item["halves"][0]["cleared"] else 0.0 for item in outcomes)
    bottom_half_clear_rate = mean(1.0 if item["halves"][1]["cleared"] else 0.0 for item in outcomes)

    profiles = []
    for profile in PROFILE_DEFINITIONS:
        picked = outcomes[_quantile_index(len(outcomes), profile["quantile"])]
        profiles.append(
            {
                "id": profile["id"],
                "label": profile["label"],
                "description": profile["description"],
                "pairScore": round(picked["pairScore"], 1),
                "pairCycles": picked["pairCycles"],
                "bothCleared": picked["bothCleared"],
                "halves": [
                    {
                        "half": half["half"],
                        "score": round(half["score"], 1),
                        "cleared": half["cleared"],
                        "cycleEquivalent": half["cycleEquivalent"],
                        "allyTurns": half["allyTurns"],
                        "enemyTurns": half["enemyTurns"],
                        "breaks": half["breaks"],
                        "durabilityRatio": half["durabilityRatio"],
                        "riskLabel": half["riskLabel"],
                        "keyMoments": half["log"][:4],
                    }
                    for half in picked["halves"]
                ],
            }
        )

    return {
        "engine": "turn_prototype_v1",
        "runs": runs,
        "overall": {
            "pairClearRate": round(pair_clear_rate, 3),
            "topHalfClearRate": round(top_half_clear_rate, 3),
            "bottomHalfClearRate": round(bottom_half_clear_rate, 3),
            "averagePairScore": round(mean(item["pairScore"] for item in outcomes), 1),
            "minPairScore": round(outcomes[0]["pairScore"], 1),
            "maxPairScore": round(outcomes[-1]["pairScore"], 1),
        },
        "profiles": profiles,
        "notes": _build_simulation_notes(pair_clear_rate, top_half_clear_rate, bottom_half_clear_rate),
    }


def _simulate_half(
    team: list[dict[str, Any]],
    half: dict[str, Any],
    mode: str,
    rng: random.Random,
) -> dict[str, Any]:
    battle = _build_battle_state(team, half, mode, rng)

    while True:
        if battle["waveIndex"] >= len(battle["waves"]):
            battle["cleared"] = True
            break
        if battle["durability"] <= 0:
            break
        if battle["currentTime"] > battle["avLimit"]:
            break
        if battle["allyTurns"] >= 80 or battle["enemyTurns"] >= 40:
            break

        actor = min(battle["actors"], key=lambda item: item["next"])
        battle["currentTime"] = actor["next"]

        if actor["kind"] == "ally":
            _handle_ally_turn(battle, actor, half, rng)
        else:
            _handle_enemy_turn(battle, actor, rng)

    cleared = battle["cleared"]
    cycle_equivalent = round(battle["currentTime"] / 260.0, 1)
    durability_ratio = round(max(0.0, min(battle["durability"] / battle["durabilityCap"], 1.0)), 2)
    tempo_score = 76.0 - cycle_equivalent * 9.5 - battle["enemyTurns"] * 1.2
    break_bonus = min(12.0, battle["breaks"] * 2.4)
    durability_bonus = durability_ratio * 18.0
    clear_bonus = 10.0 if cleared else -18.0
    score = max(0.0, min(100.0, round(tempo_score + break_bonus + durability_bonus + clear_bonus, 1)))

    return {
        "half": half["name"],
        "cleared": cleared,
        "score": score,
        "cycleEquivalent": cycle_equivalent,
        "allyTurns": battle["allyTurns"],
        "enemyTurns": battle["enemyTurns"],
        "breaks": battle["breaks"],
        "durabilityRatio": durability_ratio,
        "riskLabel": _risk_label(cleared, durability_ratio, cycle_equivalent),
        "log": battle["log"][:6],
    }


def _build_battle_state(
    team: list[dict[str, Any]],
    half: dict[str, Any],
    mode: str,
    rng: random.Random,
) -> dict[str, Any]:
    team_traits = _sum_team_traits(team)
    waves = _derive_waves(half, mode)
    durability_cap = 26.0 + team_traits.get("survival", 0.0) * 1.9 + team_traits.get("support", 0.0) * 0.45
    if any("sustain" in unit["base"]["roles"] for unit in team):
        durability_cap += 10.0

    actors = []
    for unit in team:
        speed = _ally_speed(unit)
        actors.append(
            {
                "kind": "ally",
                "id": unit["id"],
                "unit": unit,
                "speed": speed,
                "next": _initial_delay(speed, rng, ally=True),
            }
        )

    enemy_speed = waves[0]["speed"]
    actors.append(
        {
            "kind": "enemy",
            "id": "enemy",
            "speed": enemy_speed,
            "next": _initial_delay(enemy_speed, rng, ally=False),
        }
    )

    return {
        "actors": actors,
        "waves": waves,
        "waveIndex": 0,
        "currentTime": 0.0,
        "avLimit": MODE_AV_LIMIT.get(mode, 2550.0),
        "teamTraits": team_traits,
        "durabilityCap": durability_cap,
        "durability": durability_cap,
        "sp": 3,
        "spFloor": 3,
        "energy": {unit["id"]: 55.0 + rng.random() * 12.0 for unit in team},
        "effects": [],
        "vulnerability": 0.0,
        "dotPool": 0.0,
        "breakTurns": 0,
        "breaks": 0,
        "allyTurns": 0,
        "enemyTurns": 0,
        "cleared": False,
        "log": [],
    }


def _handle_ally_turn(
    battle: dict[str, Any],
    actor: dict[str, Any],
    half: dict[str, Any],
    rng: random.Random,
) -> None:
    wave = battle["waves"][battle["waveIndex"]]
    unit = actor["unit"]
    action = _choose_action(unit, battle)
    role_factor = _role_factor(unit)
    effect_damage = _effect_total(battle, "damage")
    effect_break = _effect_total(battle, "break")
    effect_guard = _effect_total(battle, "guard")
    effect_speed = _effect_total(battle, "speed")
    element_bonus = 1.12 if unit["base"]["element"] in half.get("preferredElements", []) else 1.0

    traits = unit["effective_traits"]
    target_count = wave["targets"]
    single_focus = 1.45 if target_count <= 2 else 0.88
    aoe_focus = 0.78 + 0.22 * max(target_count - 1, 0)
    base_damage = (
        traits.get("single", 0.0) * single_focus
        + traits.get("aoe", 0.0) * aoe_focus
        + traits.get("dot", 0.0) * 0.52
        + traits.get("fua", 0.0) * 0.34
        + traits.get("debuff", 0.0) * 0.18
    )
    base_damage *= 0.62 + unit["investment"] / 105.0
    action_multiplier = {"basic": 0.82, "skill": 1.14, "ultimate": 1.56}[action]
    vulnerability_bonus = 1.0 + battle["vulnerability"] + (0.18 if battle["breakTurns"] > 0 else 0.0)
    damage_roll = 0.92 + rng.random() * 0.16
    damage = base_damage * role_factor * action_multiplier * element_bonus * (1.0 + effect_damage) * vulnerability_bonus * damage_roll

    toughness_damage = (
        traits.get("break", 0.0) * 1.18
        + traits.get("single", 0.0) * 0.22
        + traits.get("aoe", 0.0) * 0.15
    )
    toughness_damage *= {"basic": 0.84, "skill": 1.12, "ultimate": 1.38}[action] * (1.0 + effect_break)
    if unit["base"]["element"] in half.get("preferredElements", []):
        toughness_damage *= 1.15

    if "support" in unit["base"]["roles"] and action in {"skill", "ultimate"}:
        battle["effects"].append(
            {
                "type": "damage",
                "value": 0.07 + traits.get("support", 0.0) * 0.008,
                "remaining": 3,
                "tick": "ally",
            }
        )
        battle["effects"].append(
            {
                "type": "speed",
                "value": 0.03 + traits.get("speed", 0.0) * 0.006,
                "remaining": 2,
                "tick": "ally",
            }
        )
        battle["effects"].append(
            {
                "type": "break",
                "value": traits.get("break", 0.0) * 0.01,
                "remaining": 2,
                "tick": "ally",
            }
        )
        if battle["allyTurns"] < 6:
            _log_event(battle, f"{unit['name']} 拉起增益，让队伍进入更顺的爆发轴。")

    if "sustain" in unit["base"]["roles"] and action in {"skill", "ultimate"}:
        recovery = 5.5 + traits.get("survival", 0.0) * 0.75 + traits.get("support", 0.0) * 0.22
        battle["durability"] = min(battle["durabilityCap"], battle["durability"] + recovery)
        battle["effects"].append(
            {
                "type": "guard",
                "value": 0.08 + traits.get("survival", 0.0) * 0.01,
                "remaining": 2,
                "tick": "enemy",
            }
        )

    if traits.get("dot", 0.0) > 0 and action != "basic":
        battle["dotPool"] = min(
            26.0,
            battle["dotPool"] + traits.get("dot", 0.0) * 0.18 * (1.0 + effect_damage),
        )

    if traits.get("debuff", 0.0) > 0 and action != "basic":
        battle["vulnerability"] = min(0.42, battle["vulnerability"] + traits.get("debuff", 0.0) * 0.006)

    if traits.get("fua", 0.0) > 0 and (action == "ultimate" or rng.random() < min(0.46, traits.get("fua", 0.0) * 0.028 + 0.06)):
        fua_damage = traits.get("fua", 0.0) * 1.5 * (1.0 + effect_damage) * (0.92 + rng.random() * 0.16)
        damage += fua_damage

    wave["hp"] -= damage
    wave["toughness"] -= toughness_damage
    if wave["toughness"] <= 0 and battle["breakTurns"] <= 0:
        break_damage = 6.0 + traits.get("break", 0.0) * 1.7 + traits.get("debuff", 0.0) * 0.4
        wave["hp"] -= break_damage
        battle["breakTurns"] = 2 if wave["targets"] <= 2 else 1
        battle["breaks"] += 1
        enemy_actor = _enemy_actor(battle)
        enemy_actor["next"] += 36.0
        _log_event(battle, f"{unit['name']} 打出破韧窗口，{half['name']} 的节奏被明显拉快。")

    if action == "ultimate":
        battle["energy"][unit["id"]] = 5.0 + traits.get("support", 0.0) * 0.8
    else:
        battle["energy"][unit["id"]] = min(
            130.0,
            battle["energy"][unit["id"]] + (22.0 if action == "basic" else 31.0) + traits.get("speed", 0.0) * 0.8,
        )

    if action == "basic":
        battle["sp"] = min(5, battle["sp"] + 1)
    elif action == "skill":
        battle["sp"] = max(0, battle["sp"] - 1)
    battle["spFloor"] = min(battle["spFloor"], battle["sp"])

    if wave["hp"] <= 0:
        _advance_wave(battle, wave["name"])

    actor["next"] = battle["currentTime"] + _action_delay(actor["speed"], effect_speed)
    battle["allyTurns"] += 1
    _tick_effects(battle, "ally")
    battle["vulnerability"] = max(0.0, battle["vulnerability"] - 0.008)
    battle["durability"] = min(battle["durabilityCap"], battle["durability"] + effect_guard * 0.35)


def _handle_enemy_turn(battle: dict[str, Any], actor: dict[str, Any], rng: random.Random) -> None:
    if battle["waveIndex"] >= len(battle["waves"]):
        return

    wave = battle["waves"][battle["waveIndex"]]
    dot_tick = battle["dotPool"] * (0.92 + rng.random() * 0.16) * (1.0 + battle["vulnerability"])
    if dot_tick > 0:
        wave["hp"] -= dot_tick
        battle["dotPool"] *= 0.88

    if wave["hp"] <= 0:
        _advance_wave(battle, wave["name"])
        actor["next"] = battle["currentTime"] + 58.0
        return

    guard = _effect_total(battle, "guard")
    pressure = wave["pressure"] * (0.9 + rng.random() * 0.22)
    pressure *= max(0.42, 1.0 - battle["teamTraits"].get("survival", 0.0) * 0.018 - guard)
    if battle["breakTurns"] > 0:
        pressure *= 0.58
        battle["breakTurns"] -= 1
        if battle["breakTurns"] == 0:
            wave["toughness"] = wave["maxToughness"]
            _log_event(battle, f"{wave['name']} 从破韧中恢复，后续行动压力会回升。")

    battle["durability"] -= pressure
    battle["enemyTurns"] += 1

    fua_counter = battle["teamTraits"].get("fua", 0.0)
    if fua_counter > 0 and rng.random() < min(0.42, fua_counter * 0.024 + 0.04):
        counter_damage = fua_counter * 1.45 * (1.0 + _effect_total(battle, "damage"))
        wave["hp"] -= counter_damage

    if wave["hp"] <= 0:
        _advance_wave(battle, wave["name"])

    actor["next"] = battle["currentTime"] + _action_delay(actor["speed"], 0.0)
    _tick_effects(battle, "enemy")
    battle["vulnerability"] = max(0.0, battle["vulnerability"] - 0.03)


def _choose_action(unit: dict[str, Any], battle: dict[str, Any]) -> str:
    roles = set(unit["base"]["roles"])
    energy = battle["energy"][unit["id"]]
    if energy >= 100.0:
        return "ultimate"
    if "support" in roles:
        if battle["sp"] > 0 and _effect_total(battle, "damage") < 0.12:
            return "skill"
        return "basic"
    if "sustain" in roles:
        low_durability = battle["durability"] < battle["durabilityCap"] * 0.72
        if battle["sp"] > 0 and low_durability:
            return "skill"
        return "basic"
    if "main_dps" in roles:
        return "skill" if battle["sp"] > 0 else "basic"
    if "sub_dps" in roles:
        return "skill" if battle["sp"] > 1 else "basic"
    return "basic"


def _advance_wave(battle: dict[str, Any], wave_name: str) -> None:
    _log_event(battle, f"{wave_name} 被清掉，队伍把节奏带进下一波。")
    battle["waveIndex"] += 1
    battle["breakTurns"] = 0
    battle["vulnerability"] *= 0.78
    battle["dotPool"] *= 0.68
    if battle["waveIndex"] >= len(battle["waves"]):
        battle["cleared"] = True
        return

    next_wave = battle["waves"][battle["waveIndex"]]
    enemy_actor = _enemy_actor(battle)
    enemy_actor["speed"] = next_wave["speed"]
    enemy_actor["next"] = battle["currentTime"] + 46.0
    _log_event(battle, f"{next_wave['name']} 入场，目标数 {next_wave['targets']}，行动压力开始抬高。")


def _derive_waves(half: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    aoe_weight = float(half["weights"].get("aoe", 0))
    single_weight = float(half["weights"].get("single", 0))
    break_target = float(half["targets"].get("break", 10))
    survival_target = float(half["targets"].get("survival", 10))
    speed_target = float(half["targets"].get("speed", 10))

    if mode == "pure_fiction":
        target_pattern = [5, 4, 5]
    elif mode == "apocalyptic_shadow":
        target_pattern = [1, 1]
    elif aoe_weight >= single_weight + 4:
        target_pattern = [3, 2]
    elif single_weight >= aoe_weight + 6:
        target_pattern = [2, 1]
    else:
        target_pattern = [3, 1]

    waves = []
    for index, targets in enumerate(target_pattern, start=1):
        hp_base = 120.0 + sum(float(value) for value in half["targets"].values()) * 2.2
        if mode == "pure_fiction":
            hp_scale = 0.88 + (index - 1) * 0.14
            pressure_scale = 0.7 + (targets - 3) * 0.08
        elif mode == "apocalyptic_shadow":
            hp_scale = 1.08 + (index - 1) * 0.12
            pressure_scale = 1.0 + (index - 1) * 0.08
        else:
            hp_scale = 0.96 + (index - 1) * 0.18
            pressure_scale = 0.9 + max(0, 2 - targets) * 0.12

        hp = hp_base * hp_scale * (0.82 + targets * 0.18)
        toughness = 22.0 + break_target * (1.18 if targets <= 2 else 0.88)
        enemy_speed = 94.0 + speed_target * 1.35 + (index - 1) * 3.0
        pressure = (7.0 + survival_target * 0.95 + targets * 0.8) * pressure_scale
        waves.append(
            {
                "name": f"{half['name']} 第 {index} 波",
                "targets": targets,
                "hp": hp,
                "toughness": toughness,
                "maxToughness": toughness,
                "speed": enemy_speed,
                "pressure": pressure,
            }
        )
    return waves


def _sum_team_traits(team: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for unit in team:
        for key, value in unit["effective_traits"].items():
            totals[key] = totals.get(key, 0.0) + float(value)
    return totals


def _ally_speed(unit: dict[str, Any]) -> float:
    roles = set(unit["base"]["roles"])
    bonus = 0.0
    if "support" in roles:
        bonus += 5.0
    if "sub_dps" in roles:
        bonus += 2.5
    if "sustain" in roles:
        bonus += 1.5
    if "main_dps" in roles:
        bonus += 1.0

    return 92.0 + unit["effective_traits"].get("speed", 0.0) * 3.9 + unit["investment"] * 0.18 + bonus


def _role_factor(unit: dict[str, Any]) -> float:
    roles = set(unit["base"]["roles"])
    if "main_dps" in roles:
        return 1.18
    if "sub_dps" in roles:
        return 1.05
    if "support" in roles:
        return 0.68
    if "sustain" in roles:
        return 0.42
    return 1.0


def _effect_total(battle: dict[str, Any], effect_type: str) -> float:
    return round(
        sum(effect["value"] for effect in battle["effects"] if effect["type"] == effect_type and effect["remaining"] > 0),
        4,
    )


def _tick_effects(battle: dict[str, Any], tick: str) -> None:
    remaining = []
    for effect in battle["effects"]:
        updated = dict(effect)
        if updated["tick"] == tick:
            updated["remaining"] -= 1
        if updated["remaining"] > 0:
            remaining.append(updated)
    battle["effects"] = remaining


def _enemy_actor(battle: dict[str, Any]) -> dict[str, Any]:
    for actor in battle["actors"]:
        if actor["kind"] == "enemy":
            return actor
    raise RuntimeError("Enemy actor missing")


def _action_delay(speed: float, speed_bonus: float) -> float:
    effective_speed = max(80.0, speed * (1.0 + speed_bonus))
    return round(10000.0 / effective_speed, 2)


def _initial_delay(speed: float, rng: random.Random, *, ally: bool) -> float:
    base = 10000.0 / speed
    if ally:
        return round(base * (0.72 + rng.random() * 0.16), 2)
    return round(base * (0.8 + rng.random() * 0.14), 2)


def _risk_label(cleared: bool, durability_ratio: float, cycle_equivalent: float) -> str:
    if not cleared:
        return "容易翻车"
    if durability_ratio >= 0.55 and cycle_equivalent <= 5.2:
        return "稳定"
    if durability_ratio >= 0.35 and cycle_equivalent <= 6.0:
        return "可接受"
    return "偏冒险"


def _build_simulation_notes(pair_clear_rate: float, top_clear_rate: float, bottom_clear_rate: float) -> list[str]:
    notes = []
    if pair_clear_rate >= 0.8:
        notes.append("这套双队在当前原型模拟里稳定性较高。")
    elif pair_clear_rate >= 0.55:
        notes.append("这套双队能打，但手顺和随机波动会明显影响结果。")
    else:
        notes.append("这套双队在原型模拟里波动偏大，建议更多看静态推荐与替补。")

    gap = top_clear_rate - bottom_clear_rate
    if gap >= 0.15:
        notes.append("下半比上半更像压力点，后续可以优先补强下半轴。")
    elif gap <= -0.15:
        notes.append("上半比下半更吃操作和出手顺序。")
    else:
        notes.append("上下半的容错差距不大，主要看整体节奏。")
    return notes


def _quantile_index(length: int, quantile: float) -> int:
    if length <= 1:
        return 0
    return max(0, min(length - 1, int(round((length - 1) * quantile))))


def _stable_seed(*parts: str) -> int:
    seed = 23
    for part in parts:
        for char in part:
            seed = (seed * 131 + ord(char)) % 2_147_483_647
    return seed


def _log_event(battle: dict[str, Any], message: str) -> None:
    if len(battle["log"]) < 10 and message not in battle["log"]:
        battle["log"].append(message)
