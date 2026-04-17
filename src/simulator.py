from __future__ import annotations

import random
from statistics import mean
from typing import Any

from src.data_loader import load_simulation_profiles

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
    "pure_fiction": 2500.0,
    "apocalyptic_shadow": 2480.0,
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
            "engine": "turn_prototype_v4",
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
        "engine": "turn_prototype_v4",
    }


def _simulate_pair_result(
    scenario: dict[str, Any],
    result: dict[str, Any],
    roster_by_id: dict[str, dict[str, Any]],
    *,
    runs: int,
    pair_seed: int,
) -> dict[str, Any]:
    profiles = load_simulation_profiles().get(scenario["id"], {})
    team_bundles = []
    for team, half in zip(result["teams"], scenario["halves"]):
        units = [roster_by_id[unit_id] for unit_id in team["characterIds"] if unit_id in roster_by_id]
        team_bundles.append(
            {
                "team": team,
                "half": half,
                "profile": profiles.get(half["key"], {}),
                "units": units,
            }
        )

    outcomes: list[dict[str, Any]] = []
    for run_index in range(runs):
        rng = random.Random(pair_seed + run_index * 7919)
        halves = [
            _simulate_half(bundle["units"], bundle["half"], scenario["mode"], bundle["profile"], rng)
            for bundle in team_bundles
        ]

        both_cleared = all(half["cleared"] for half in halves)
        diff_penalty = abs(halves[0]["score"] - halves[1]["score"]) / 10.0
        if scenario["mode"] == "pure_fiction":
            pair_score = round((halves[0]["score"] + halves[1]["score"]) / 2.0 + (4.0 if both_cleared else 0.0) - diff_penalty * 0.8, 1)
            pair_cycles = round((halves[0]["cycleEquivalent"] + halves[1]["cycleEquivalent"]) / 2.0, 1)
        else:
            pair_score = round((halves[0]["score"] + halves[1]["score"]) / 2.0 + (6.0 if both_cleared else -8.0) - diff_penalty, 1)
            pair_cycles = round(max(halves[0]["cycleEquivalent"], halves[1]["cycleEquivalent"]), 1)

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

    profiles_payload = []
    for profile in PROFILE_DEFINITIONS:
        picked = outcomes[_quantile_index(len(outcomes), profile["quantile"])]
        profiles_payload.append(
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
                        "interruptsUsed": half["interruptsUsed"],
                        "dangerousSkillsSeen": half["dangerousSkillsSeen"],
                        "phaseTransitions": half["phaseTransitions"],
                        "specialMetric": half.get("specialMetric"),
                        "keyMoments": _select_key_moments(half["log"]),
                    }
                    for half in picked["halves"]
                ],
            }
        )

    return {
        "engine": "turn_prototype_v3",
        "runs": runs,
        "overall": {
            "pairClearRate": round(pair_clear_rate, 3),
            "topHalfClearRate": round(top_half_clear_rate, 3),
            "bottomHalfClearRate": round(bottom_half_clear_rate, 3),
            "averagePairScore": round(mean(item["pairScore"] for item in outcomes), 1),
            "minPairScore": round(outcomes[0]["pairScore"], 1),
            "maxPairScore": round(outcomes[-1]["pairScore"], 1),
            "averageInterrupts": round(
                mean(sum(half["interruptsUsed"] for half in item["halves"]) for item in outcomes),
                1,
            ),
            "averageDangerousSkills": round(
                mean(sum(half["dangerousSkillsSeen"] for half in item["halves"]) for item in outcomes),
                1,
            ),
        },
        "profiles": profiles_payload,
        "notes": _build_simulation_notes(scenario["mode"], pair_clear_rate, top_half_clear_rate, bottom_half_clear_rate),
    }


def _simulate_half(
    team: list[dict[str, Any]],
    half: dict[str, Any],
    mode: str,
    profile: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    battle = _build_battle_state(team, half, mode, profile, rng)

    while True:
        if battle["durability"] <= 0:
            break
        if battle["currentTime"] > battle["avLimit"]:
            break
        if battle["allyTurns"] >= 96 or battle["enemyTurns"] >= 52:
            break
        if battle["waveIndex"] >= len(battle["waves"]):
            if battle["goal"] == "points":
                break
            battle["cleared"] = True
            break

        actor = min(battle["actors"], key=lambda item: item["next"])
        battle["currentTime"] = actor["next"]

        if actor["kind"] == "ally":
            _handle_ally_turn(battle, actor, half, rng)
        else:
            _run_interrupt_window(battle, actor, half, rng)
            if battle["durability"] <= 0 or battle["waveIndex"] >= len(battle["waves"]):
                continue
            _handle_enemy_turn(battle, actor, rng)

    return _summarize_half(battle, half, mode)


def _build_battle_state(
    team: list[dict[str, Any]],
    half: dict[str, Any],
    mode: str,
    profile: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    team_traits = _sum_team_traits(team)
    waves = _derive_waves(half, mode, profile)
    team_flags = _team_flags(team)
    primary_carry = _primary_carry_id(team)

    durability_cap = 22.0 + team_traits.get("survival", 0.0) * 1.85 + team_traits.get("support", 0.0) * 0.4
    if any("sustain" in unit["base"]["roles"] for unit in team):
        durability_cap += 9.0
    if mode == "pure_fiction":
        durability_cap *= 0.92

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

    enemy_speed = waves[0]["speed"] if waves else 100.0
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
        "mode": mode,
        "goal": profile.get("goal", "clear"),
        "goalScore": float(profile.get("scoreTarget", 0.0)),
        "profile": profile,
        "profileBuffs": profile.get("buffs", {}),
        "teamTraits": team_traits,
        "teamFlags": team_flags,
        "primaryCarryId": primary_carry,
        "durabilityCap": durability_cap,
        "durability": durability_cap,
        "sp": 3,
        "spFloor": 3,
        "energy": {unit["id"]: 52.0 + rng.random() * 16.0 for unit in team},
        "effects": [],
        "vulnerability": 0.0,
        "dotPool": 0.0,
        "breakTurns": 0,
        "breaks": 0,
        "allyTurns": 0,
        "enemyTurns": 0,
        "interruptsUsed": 0,
        "dangerousSkillsSeen": 0,
        "cleared": False,
        "scorePoints": 0.0,
        "killCount": 0,
        "combo": 0.0,
        "gauges": {
            "acheron_stacks": 3 if "acheron" in {unit["id"] for unit in team} else 0,
        },
        "log": [],
    }


def _handle_ally_turn(
    battle: dict[str, Any],
    actor: dict[str, Any],
    half: dict[str, Any],
    rng: random.Random,
    *,
    action_override: str | None = None,
    interrupt: bool = False,
    interrupt_reason: str | None = None,
) -> None:
    if battle["waveIndex"] >= len(battle["waves"]):
        return

    wave = battle["waves"][battle["waveIndex"]]
    unit = actor["unit"]
    uid = unit["id"]
    traits = unit["effective_traits"]
    action = action_override or _choose_action(unit, battle)
    role_factor = _role_factor(unit)
    effect_damage = _effect_total(battle, "damage")
    effect_break = _effect_total(battle, "break")
    effect_guard = _effect_total(battle, "guard")
    effect_speed = _effect_total(battle, "speed")
    effect_fua = _effect_total(battle, "fua")
    effect_dot = _effect_total(battle, "dot")
    effect_super_break = _effect_total(battle, "super_break")
    element_bonus = 1.12 if unit["base"]["element"] in half.get("preferredElements", []) else 1.0
    profile_bonus = _profile_damage_bonus(battle["profileBuffs"], traits, wave)

    target_count = max(1, int(wave["remainingTargets"]))
    single_focus = 1.55 if target_count <= 2 else 0.82
    aoe_focus = 0.66 + 0.24 * max(target_count - 1, 0)
    base_damage = (
        traits.get("single", 0.0) * single_focus
        + traits.get("aoe", 0.0) * aoe_focus
        + traits.get("dot", 0.0) * 0.38
        + traits.get("fua", 0.0) * 0.3
        + traits.get("debuff", 0.0) * 0.18
        + traits.get("support", 0.0) * 0.05
    )
    base_damage *= 0.58 + unit["investment"] / 103.0
    action_multiplier = {"basic": 0.8, "skill": 1.14, "ultimate": 1.56}[action]
    vulnerability_bonus = 1.0 + battle["vulnerability"] + (0.14 if battle["breakTurns"] > 0 else 0.0)
    damage_roll = 0.92 + rng.random() * 0.16
    damage = base_damage * role_factor * action_multiplier * element_bonus * (1.0 + effect_damage + profile_bonus) * vulnerability_bonus * damage_roll

    toughness_damage = (
        traits.get("break", 0.0) * 1.14
        + traits.get("single", 0.0) * 0.22
        + traits.get("aoe", 0.0) * 0.12
    )
    toughness_damage *= {"basic": 0.84, "skill": 1.12, "ultimate": 1.4}[action] * (1.0 + effect_break)
    toughness_damage *= 1.0 + float(battle["profileBuffs"].get("breakBonus", 0.0))
    if unit["base"]["element"] in half.get("preferredElements", []):
        toughness_damage *= 1.15

    if "support" in unit["base"]["roles"] and action in {"skill", "ultimate"}:
        _apply_effect(battle, "damage", 0.07 + traits.get("support", 0.0) * 0.008, 3, "ally")
        _apply_effect(battle, "speed", 0.03 + traits.get("speed", 0.0) * 0.005, 2, "ally")
        _apply_effect(battle, "break", traits.get("break", 0.0) * 0.01, 2, "ally")
        if battle["allyTurns"] < 6:
            _log_event(battle, f"{unit['name']} 拉起团队增益，出手轴开始变顺。")

    if "sustain" in unit["base"]["roles"] and action in {"skill", "ultimate"}:
        recovery = 5.2 + traits.get("survival", 0.0) * 0.74 + traits.get("support", 0.0) * 0.2
        battle["durability"] = min(battle["durabilityCap"], battle["durability"] + recovery)
        _apply_effect(battle, "guard", 0.08 + traits.get("survival", 0.0) * 0.01, 2, "enemy")

    if traits.get("dot", 0.0) > 0 and action != "basic":
        battle["dotPool"] = min(40.0, battle["dotPool"] + traits.get("dot", 0.0) * 0.18 * (1.0 + effect_dot))

    if traits.get("debuff", 0.0) > 0 and action != "basic":
        battle["vulnerability"] = min(0.58, battle["vulnerability"] + traits.get("debuff", 0.0) * 0.006)

    extra_damage, extra_toughness = _apply_unit_specials(
        battle,
        actor,
        action,
        wave,
        effect_break=effect_break,
        effect_fua=effect_fua,
        effect_dot=effect_dot,
        effect_super_break=effect_super_break,
        rng=rng,
    )
    damage += extra_damage
    toughness_damage += extra_toughness

    if traits.get("fua", 0.0) > 0 and (
        action == "ultimate"
        or rng.random() < min(0.52, traits.get("fua", 0.0) * 0.028 + effect_fua * 0.5 + 0.05)
    ):
        fua_damage = traits.get("fua", 0.0) * (1.36 + effect_fua) * (1.0 + effect_damage) * (0.92 + rng.random() * 0.16)
        if battle["teamFlags"]["fua_core"]:
            fua_damage *= 1.12
        damage += fua_damage

    _apply_hit_to_wave(battle, wave, half, damage, toughness_damage, unit["name"], uid, rng)

    if action == "ultimate":
        battle["energy"][uid] = 8.0 + traits.get("support", 0.0) * 0.8
    else:
        battle["energy"][uid] = min(
            130.0,
            battle["energy"][uid] + (21.0 if action == "basic" else 31.0) + traits.get("speed", 0.0) * 0.9,
        )

    if action == "basic":
        battle["sp"] = min(5, battle["sp"] + 1)
    elif action == "skill":
        battle["sp"] = max(0, battle["sp"] - 1)
    battle["spFloor"] = min(battle["spFloor"], battle["sp"])

    if interrupt:
        battle["interruptsUsed"] += 1
        if interrupt_reason:
            _log_event(battle, f"{unit['name']} 抢在敌方{interrupt_reason}前插入终结技。")
    else:
        actor["next"] = battle["currentTime"] + _action_delay(actor["speed"], effect_speed)
        battle["allyTurns"] += 1
        _tick_effects(battle, "ally")
        battle["vulnerability"] = max(0.0, battle["vulnerability"] - 0.01)
        battle["durability"] = min(battle["durabilityCap"], battle["durability"] + effect_guard * 0.3)


def _handle_enemy_turn(battle: dict[str, Any], actor: dict[str, Any], rng: random.Random) -> None:
    if battle["waveIndex"] >= len(battle["waves"]):
        return

    wave = battle["waves"][battle["waveIndex"]]
    _maybe_trigger_phase_transitions(battle, wave)
    _spawn_summon_if_needed(battle, wave, rng)

    dot_tick = battle["dotPool"] * (0.9 + rng.random() * 0.18) * (1.0 + battle["vulnerability"])
    if dot_tick > 0:
        wave["hp"] -= dot_tick
        battle["dotPool"] *= 0.88
        _register_enemy_losses(battle, wave, rng)
        if battle["waveIndex"] < len(battle["waves"]) and battle["waves"][battle["waveIndex"]] is wave and wave["hp"] > 0:
            _maybe_trigger_phase_transitions(battle, wave)

    if battle["waveIndex"] >= len(battle["waves"]):
        actor["next"] = battle["currentTime"] + 58.0
        return

    wave = battle["waves"][battle["waveIndex"]]
    action_plan = _resolve_enemy_action(battle, wave)
    guard = _effect_total(battle, "guard")
    effect_fua = _effect_total(battle, "fua")
    pressure_roll = 0.9 + rng.random() * 0.2
    target_scale = 0.72 + wave["remainingTargets"] * 0.18
    pressure = wave["pressure"] * pressure_roll * target_scale
    pressure += wave.get("summonAttackPressure", wave.get("summonPressure", 0.0)) * wave.get("summonCount", 0)
    guard_factor = max(0.36, 1.0 - battle["teamTraits"].get("survival", 0.0) * 0.018 - guard)
    pressure *= guard_factor

    if wave["archetype"] == "boss" and _wave_hp_ratio(wave) <= float(wave.get("berserkAt", 0.0) or 0.0):
        pressure *= 1.18

    if battle["breakTurns"] > 0:
        pressure *= 0.56
        battle["breakTurns"] -= 1
        if battle["breakTurns"] == 0:
            wave["toughness"] = wave["maxToughness"]
            _log_event(battle, f"{wave['name']} 从破韧里恢复，敌方节奏重新抬头。")

    if action_plan["kind"] == "charge":
        pressure *= float(action_plan.get("chargePressureMultiplier", 0.58))
        _log_event(battle, f"{wave['name']} 正在蓄力 {action_plan['name']}，下一轮敌方压力会明显变高。")
    elif action_plan["kind"] == "danger":
        if action_plan.get("ignoreGuard"):
            pressure = wave["pressure"] * pressure_roll * target_scale * max(
                0.5, 1.0 - battle["teamTraits"].get("survival", 0.0) * 0.014
            )
        pressure = pressure * float(action_plan.get("pressureMultiplier", 1.6)) + float(action_plan.get("flatPressure", 0.0))
        battle["dangerousSkillsSeen"] += 1
        _log_event(battle, f"{wave['name']} 释放了危险技能 {action_plan['name']}，队伍需要硬吃一轮高压。")
        if float(action_plan.get("delayAllies", 0.0)) > 0:
            _delay_allies(battle, float(action_plan["delayAllies"]))
        if int(action_plan.get("summonTargets", 0)) > 0:
            _spawn_specific_summons(
                battle,
                wave,
                int(action_plan["summonTargets"]),
                summon_hp=float(action_plan.get("summonHp", wave.get("summonHp", wave["unitHp"] * 0.55))),
                pressure=float(action_plan.get("summonPressure", wave.get("summonPressure", 0.0))),
            )

    battle["durability"] -= pressure
    battle["enemyTurns"] += 1

    counter_damage = 0.0
    if battle["teamFlags"]["aventurine"] and rng.random() < 0.26:
        counter_damage += 4.0 + battle["teamTraits"].get("fua", 0.0) * 0.18
    if battle["teamFlags"]["fua_core"] and rng.random() < min(0.46, battle["teamTraits"].get("fua", 0.0) * 0.018 + effect_fua * 0.45):
        counter_damage += battle["teamTraits"].get("fua", 0.0) * 0.85 * (1.0 + effect_fua)

    if counter_damage > 0:
        wave["hp"] -= counter_damage
        _register_enemy_losses(battle, wave, rng)
        if battle["waveIndex"] < len(battle["waves"]) and battle["waves"][battle["waveIndex"]] is wave and wave["hp"] > 0:
            _maybe_trigger_phase_transitions(battle, wave)

    actor["next"] = battle["currentTime"] + _action_delay(actor["speed"], 0.0)
    _tick_effects(battle, "enemy")
    battle["vulnerability"] = max(0.0, battle["vulnerability"] - 0.03)
    battle["combo"] = max(0.0, battle["combo"] - (0.55 if battle["goal"] == "points" else 0.2))


def _run_interrupt_window(
    battle: dict[str, Any],
    enemy_actor: dict[str, Any],
    half: dict[str, Any],
    rng: random.Random,
) -> None:
    if battle["waveIndex"] >= len(battle["waves"]):
        return

    wave = battle["waves"][battle["waveIndex"]]
    threat = _peek_enemy_action_kind(wave)
    if threat == "normal":
        return

    used_ids: set[str] = set()
    for _ in range(2):
        actor = _choose_interrupt_actor(battle, wave, used_ids)
        if not actor:
            return
        used_ids.add(actor["id"])
        _handle_ally_turn(
            battle,
            actor,
            half,
            rng,
            action_override="ultimate",
            interrupt=True,
            interrupt_reason="危险技能" if threat == "danger" else "蓄力动作",
        )
        if battle["waveIndex"] >= len(battle["waves"]) or battle["durability"] <= 0:
            return
        wave = battle["waves"][battle["waveIndex"]]
        if _peek_enemy_action_kind(wave) == "normal":
            return


def _choose_interrupt_actor(
    battle: dict[str, Any],
    wave: dict[str, Any],
    used_ids: set[str],
) -> dict[str, Any] | None:
    threat = _peek_enemy_action_kind(wave)
    durability_ratio = battle["durability"] / max(battle["durabilityCap"], 1.0)
    candidates: list[tuple[float, dict[str, Any]]] = []
    for actor in battle["actors"]:
        if actor["kind"] != "ally":
            continue
        if actor["id"] in used_ids:
            continue
        if battle["energy"].get(actor["id"], 0.0) < 100.0:
            continue
        unit = actor["unit"]
        roles = set(unit["base"]["roles"])
        traits = unit["effective_traits"]
        priority = 0.0
        if threat == "danger":
            if "support" in roles:
                priority += 11.0 + traits.get("support", 0.0) * 0.35
            if "sustain" in roles:
                priority += 12.0 + traits.get("survival", 0.0) * 0.45
            if "main_dps" in roles:
                priority += 8.0 + traits.get("single", 0.0) * 0.25 + traits.get("aoe", 0.0) * 0.15
        else:
            if "main_dps" in roles:
                priority += 9.0 + traits.get("break", 0.0) * 0.3 + traits.get("single", 0.0) * 0.22
            if "support" in roles:
                priority += 6.0 + traits.get("support", 0.0) * 0.28
        if battle["breakTurns"] > 0 and actor["id"] in {"firefly", "acheron", "kafka", "dr_ratio"}:
            priority += 5.0
        if actor["id"] in {"robin", "sparkle", "huohuo"} and durability_ratio < 0.7:
            priority += 4.0
        if actor["id"] == "trailblazer_harmony" and battle["teamFlags"]["super_break_core"]:
            priority += 3.5
        if actor["id"] == "acheron" and battle["gauges"].get("acheron_stacks", 0) >= 7:
            priority += 5.0
        if actor["id"] == battle["primaryCarryId"]:
            priority += 1.5
        if priority >= 9.5:
            candidates.append((priority, actor))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _peek_enemy_action_kind(wave: dict[str, Any]) -> str:
    danger = wave.get("dangerousSkill") or {}
    if not danger:
        return "normal"
    if wave.get("dangerChargeRemaining", 0) > 1:
        return "charge"
    if wave.get("dangerChargeRemaining", 0) == 1:
        return "danger"
    if wave.get("dangerTurnsUntilTrigger", 999) <= 1:
        return "charge" if int(danger.get("chargeTurns", 0)) > 0 else "danger"
    return "normal"


def _resolve_enemy_action(battle: dict[str, Any], wave: dict[str, Any]) -> dict[str, Any]:
    wave["enemyTurnCounter"] += 1
    danger = dict(wave.get("dangerousSkill") or {})
    if not danger:
        return {"kind": "normal", "name": "普通攻击"}

    if wave.get("dangerChargeRemaining", 0) > 1:
        wave["dangerChargeRemaining"] -= 1
        return {"kind": "charge", **danger}
    if wave.get("dangerChargeRemaining", 0) == 1:
        wave["dangerChargeRemaining"] = 0
        return {"kind": "danger", **danger}

    if wave.get("dangerTurnsUntilTrigger", 999) <= 1:
        cycle = max(int(danger.get("cycle", 3)), 1)
        charge_turns = max(int(danger.get("chargeTurns", 0)), 0)
        wave["dangerTurnsUntilTrigger"] = cycle
        if charge_turns > 0:
            wave["dangerChargeRemaining"] = charge_turns
            return {"kind": "charge", **danger}
        return {"kind": "danger", **danger}

    wave["dangerTurnsUntilTrigger"] = max(1, wave.get("dangerTurnsUntilTrigger", 999) - 1)
    return {"kind": "normal", "name": "普通攻击"}


def _delay_allies(battle: dict[str, Any], amount: float) -> None:
    for actor in battle["actors"]:
        if actor["kind"] != "ally":
            continue
        actor["next"] += amount


def _maybe_trigger_phase_transitions(battle: dict[str, Any], wave: dict[str, Any]) -> None:
    transitions = wave.get("phaseTransitions") or []
    while wave["hp"] > 0 and wave.get("phaseIndex", 0) < len(transitions):
        transition = transitions[wave["phaseIndex"]]
        if _wave_hp_ratio(wave) > float(transition.get("at", 0.0)):
            return
        wave["phaseIndex"] += 1
        if "pressureSet" in transition:
            wave["pressure"] = float(transition["pressureSet"])
        else:
            wave["pressure"] = wave["pressure"] * float(transition.get("pressureMultiplier", 1.0)) + float(
                transition.get("pressureFlat", 0.0)
            )
        if "speedSet" in transition:
            wave["speed"] = float(transition["speedSet"])
        else:
            wave["speed"] += float(transition.get("speedBonus", 0.0))
        if "summonTargetsMax" in transition:
            wave["summonTargetsMax"] = int(transition["summonTargetsMax"])
        if "summonAttackPressure" in transition or "summonPressure" in transition:
            wave["summonAttackPressure"] = float(
                transition.get("summonAttackPressure", transition.get("summonPressure", wave.get("summonAttackPressure", 0.0)))
            )
        if transition.get("clearSummons"):
            wave["summonCount"] = 0
            wave["remainingTargets"] = wave["mainTargetsAlive"]
        if float(transition.get("toughnessRefill", 0.0)) > 0:
            refill = wave["maxToughness"] * float(transition["toughnessRefill"])
            wave["toughness"] = max(wave["toughness"], refill)
        if "toughnessSet" in transition:
            wave["maxToughness"] = float(transition["toughnessSet"])
            wave["toughness"] = max(wave["toughness"], wave["maxToughness"])
        if float(transition.get("restoreHpRatio", 0.0)) > 0:
            wave["hp"] += _alive_hp_capacity(wave) * float(transition["restoreHpRatio"])
        if int(transition.get("summonTargets", 0)) > 0:
            _spawn_specific_summons(
                battle,
                wave,
                int(transition["summonTargets"]),
                summon_hp=float(transition.get("summonHp", wave.get("summonHp", wave["unitHp"] * 0.55))),
                pressure=float(transition.get("summonAttackPressure", transition.get("summonPressure", wave.get("summonAttackPressure", 0.0)))),
            )
        if isinstance(transition.get("dangerousSkill"), dict):
            wave["dangerousSkill"] = dict(transition["dangerousSkill"])
            wave["dangerStartTurns"] = max(
                1,
                int(wave["dangerousSkill"].get("firstAt", wave["dangerousSkill"].get("cycle", 3))),
            )
            wave["dangerTurnsUntilTrigger"] = wave["dangerStartTurns"]
            wave["dangerChargeRemaining"] = 0
        if transition.get("dangerSoon"):
            wave["dangerTurnsUntilTrigger"] = 1
        if transition.get("dangerCharge"):
            wave["dangerChargeRemaining"] = max(1, int(transition["dangerCharge"]))
        wave["hp"] = min(wave["hp"], _alive_hp_capacity(wave))
        enemy_actor = _enemy_actor(battle)
        enemy_actor["speed"] = wave["speed"]
        if float(transition.get("delayEnemy", 0.0)) > 0:
            enemy_actor["next"] += float(transition["delayEnemy"])
        if float(transition.get("advanceEnemy", 0.0)) > 0:
            enemy_actor["next"] = max(
                battle["currentTime"] + 1.0,
                enemy_actor["next"] * max(0.1, 1.0 - float(transition["advanceEnemy"])),
            )
        _log_event(battle, transition.get("name", f"{wave['name']} 进入新的阶段，敌方机制开始变化。"))


def _spawn_specific_summons(
    battle: dict[str, Any],
    wave: dict[str, Any],
    amount: int,
    *,
    summon_hp: float,
    pressure: float,
) -> None:
    max_targets = int(wave.get("summonTargetsMax", wave["baseTargets"]))
    can_spawn = max(0, max_targets - wave["remainingTargets"])
    spawned = min(can_spawn, max(0, amount))
    if spawned <= 0:
        return
    wave["summonCount"] += spawned
    wave["remainingTargets"] += spawned
    wave["targets"] = max(wave["targets"], wave["remainingTargets"])
    wave["hp"] += summon_hp * spawned
    wave["summonHp"] = max(wave.get("summonHp", summon_hp), summon_hp)
    wave["summonAttackPressure"] = max(wave.get("summonAttackPressure", 0.0), pressure)
    _log_event(battle, f"{wave['name']} 召出了 {spawned} 个额外目标，场面压力继续抬升。")


def _apply_unit_specials(
    battle: dict[str, Any],
    actor: dict[str, Any],
    action: str,
    wave: dict[str, Any],
    *,
    effect_break: float,
    effect_fua: float,
    effect_dot: float,
    effect_super_break: float,
    rng: random.Random,
) -> tuple[float, float]:
    unit = actor["unit"]
    uid = unit["id"]
    traits = unit["effective_traits"]
    extra_damage = 0.0
    extra_toughness = 0.0

    if uid == "robin" and action in {"skill", "ultimate"}:
        _apply_effect(battle, "damage", 0.12 + traits.get("support", 0.0) * 0.005, 3, "ally")
        _apply_effect(battle, "speed", 0.05, 2, "ally")
        _apply_effect(battle, "fua", 0.08, 3, "ally")
        if action == "ultimate":
            _advance_allies(battle, 0.18, exclude_id=uid)
            _log_event(battle, "罗宾开大后把全队推上新的爆发窗口。")

    if uid == "sparkle" and action in {"skill", "ultimate"}:
        _apply_effect(battle, "damage", 0.1, 3, "ally")
        _apply_effect(battle, "speed", 0.06, 2, "ally")
        battle["sp"] = min(5, battle["sp"] + 2)
        if battle["primaryCarryId"] and battle["primaryCarryId"] != uid:
            _advance_actor(battle, battle["primaryCarryId"], 0.22)
        _log_event(battle, "花火回了一口战技点，并把主核出手继续往前推。")

    if uid == "huohuo" and action in {"skill", "ultimate"}:
        energy_gain = 8.0 if action == "skill" else 16.0
        for ally_id in battle["energy"]:
            if ally_id != uid:
                battle["energy"][ally_id] = min(130.0, battle["energy"][ally_id] + energy_gain)

    if uid == "trailblazer_harmony" and action != "basic":
        _apply_effect(battle, "super_break", 0.22 + traits.get("break", 0.0) * 0.01, 3, "ally")

    if uid == "gallagher":
        if action != "basic":
            _apply_effect(battle, "guard", 0.06, 2, "enemy")
            extra_toughness += traits.get("break", 0.0) * 0.35
        if battle["breakTurns"] > 0:
            extra_damage += 3.5 + traits.get("break", 0.0) * 0.45

    if uid == "aventurine" and action in {"skill", "ultimate"}:
        _apply_effect(battle, "guard", 0.16, 3, "enemy")
        _apply_effect(battle, "fua", 0.06, 3, "enemy")

    if uid == "black_swan":
        battle["dotPool"] = min(42.0, battle["dotPool"] + traits.get("dot", 0.0) * 0.34 * (1.0 + effect_dot))
        battle["vulnerability"] = min(0.58, battle["vulnerability"] + 0.03)

    if uid == "kafka" and action != "basic" and battle["dotPool"] > 0:
        detonation = battle["dotPool"] * (0.58 if action == "skill" else 0.84) * (1.0 + effect_dot)
        extra_damage += detonation
        battle["dotPool"] *= 0.72
        if battle["teamFlags"]["dot_core"]:
            battle["vulnerability"] = min(0.58, battle["vulnerability"] + 0.02)
        _log_event(battle, "卡芙卡把挂好的持续伤害提前引爆，清场效率明显上去了。")

    if uid == "firefly":
        if action != "basic":
            extra_toughness += traits.get("break", 0.0) * 0.85
        if (battle["breakTurns"] > 0 or wave["toughness"] <= wave["maxToughness"] * 0.28) and effect_super_break > 0:
            extra_damage += traits.get("break", 0.0) * (2.0 + effect_super_break * 2.2) * (1.0 + effect_break)
            _log_event(battle, "流萤在破韧窗口里打出了额外超击破伤害。")

    if uid == "acheron":
        gain = 1 if action == "basic" else 2
        if action != "basic" and traits.get("debuff", 0.0) >= 8:
            gain += 1
        if battle["teamFlags"]["acheron_core"] and action != "basic":
            gain += 1
        battle["gauges"]["acheron_stacks"] += gain
        if battle["gauges"]["acheron_stacks"] >= 9:
            procs = int(battle["gauges"]["acheron_stacks"] // 9)
            battle["gauges"]["acheron_stacks"] = battle["gauges"]["acheron_stacks"] % 9
            extra_damage += procs * (22.0 + traits.get("single", 0.0) * 1.6 + traits.get("aoe", 0.0) * 0.7)
            battle["vulnerability"] = min(0.58, battle["vulnerability"] + 0.04)
            _log_event(battle, "黄泉层数成型后提前打出了一轮高额终结技伤害。")

    if uid == "dr_ratio" and action != "basic":
        if battle["vulnerability"] >= 0.08 or battle["teamFlags"]["ratio_topaz"]:
            extra_damage += traits.get("fua", 0.0) * (1.55 + effect_fua) * (0.94 + rng.random() * 0.12)

    if uid == "topaz" and action != "basic":
        _apply_effect(battle, "fua", 0.1 + traits.get("fua", 0.0) * 0.004, 3, "ally")
        battle["vulnerability"] = min(0.58, battle["vulnerability"] + 0.02)

    if uid in {"himeko", "herta"} and wave["remainingTargets"] >= 3:
        extra_damage += traits.get("fua", 0.0) * 0.7 * (1.0 + effect_fua)

    return round(extra_damage, 2), round(extra_toughness, 2)


def _apply_hit_to_wave(
    battle: dict[str, Any],
    wave: dict[str, Any],
    half: dict[str, Any],
    damage: float,
    toughness_damage: float,
    source_name: str,
    source_id: str,
    rng: random.Random,
) -> None:
    wave["hp"] -= damage
    wave["toughness"] -= toughness_damage

    if wave["toughness"] <= 0 and battle["breakTurns"] <= 0:
        break_damage = 6.0 + battle["teamTraits"].get("break", 0.0) * 0.18
        break_damage += float(battle["profileBuffs"].get("breakWindowBonus", 0.0)) * 20.0
        wave["hp"] -= break_damage
        battle["breakTurns"] = 2 if wave["archetype"] == "boss" or wave["remainingTargets"] <= 2 else 1
        battle["breaks"] += 1
        enemy_actor = _enemy_actor(battle)
        enemy_actor["next"] += 40.0 if wave["archetype"] == "boss" else 28.0
        _log_event(battle, f"{source_name} 打出了破韧窗口，{half['name']} 的压力明显下降。")

    _register_enemy_losses(battle, wave, rng, source_id=source_id)
    if battle["waveIndex"] < len(battle["waves"]) and battle["waves"][battle["waveIndex"]] is wave and wave["hp"] > 0:
        _maybe_trigger_phase_transitions(battle, wave)


def _register_enemy_losses(
    battle: dict[str, Any],
    wave: dict[str, Any],
    rng: random.Random,
    *,
    source_id: str | None = None,
) -> None:
    wave["hp"] = max(0.0, wave["hp"])
    while wave["remainingTargets"] > 0:
        defeated = _next_defeated_target(wave)
        if not defeated:
            break
        threshold = _alive_hp_capacity(wave) - defeated["hp"]
        if wave["hp"] > threshold + 1e-6:
            break

        if defeated["kind"] == "summon":
            wave["summonCount"] -= 1
        else:
            wave["mainTargetsAlive"] -= 1
        wave["remainingTargets"] = max(0, wave["mainTargetsAlive"] + wave["summonCount"])
        battle["killCount"] += 1
        gained = wave["killScore"] * (1.0 + min(battle["combo"], 6.0) * 0.05)
        battle["scorePoints"] += gained
        battle["combo"] += 1.0

        if wave["remainingTargets"] > 0 and battle["teamFlags"]["fua_core"]:
            wave["hp"] -= 2.4 + battle["teamTraits"].get("fua", 0.0) * 0.22 + _effect_total(battle, "fua") * 5.0

        if wave["remainingTargets"] > 0 and battle["teamFlags"]["himeko_herta"]:
            wave["hp"] -= 3.0 + battle["teamTraits"].get("aoe", 0.0) * 0.18 + battle["teamTraits"].get("fua", 0.0) * 0.12
            if source_id in {"himeko", "herta"} or battle["mode"] == "pure_fiction":
                _log_event(battle, "姬子 / 黑塔连锁追击开始滚雪球，剩余小怪血线被迅速压低。")

        if wave["mainTargetsAlive"] <= 0 and wave.get("clearSummonsOnMainDeath", False):
            wave["summonCount"] = 0
            wave["remainingTargets"] = 0
            _resolve_wave_completion(battle, wave)
            return

        if wave["remainingTargets"] <= 0:
            _resolve_wave_completion(battle, wave)
            return


def _resolve_wave_completion(battle: dict[str, Any], wave: dict[str, Any]) -> None:
    if wave["respawnsRemaining"] > 0:
        wave["respawnsRemaining"] -= 1
        wave["respawnsUsed"] += 1
        wave["mainTargetsAlive"] = wave["baseTargets"]
        wave["summonCount"] = 0
        wave["remainingTargets"] = wave["baseTargets"]
        wave["targets"] = wave["baseTargets"]
        wave["unitHp"] *= wave["respawnScale"]
        wave["hp"] = wave["unitHp"] * wave["remainingTargets"]
        wave["toughness"] = wave["maxToughness"] * min(1.2, 1.0 + wave["respawnsUsed"] * 0.05)
        wave["maxToughness"] = wave["toughness"]
        wave["pressure"] = wave["basePressure"]
        wave["speed"] = wave["baseSpeed"]
        wave["phaseIndex"] = 0
        wave["enemyTurnCounter"] = 0
        wave["dangerTurnsUntilTrigger"] = wave.get("dangerStartTurns", 999)
        wave["dangerChargeRemaining"] = 0
        battle["breakTurns"] = 0
        _log_event(battle, f"{wave['name']} 重新补位，刷分波继续进场。")
        return

    _advance_wave(battle, wave["name"])


def _advance_wave(battle: dict[str, Any], wave_name: str) -> None:
    _log_event(battle, f"{wave_name} 被清掉，队伍把节奏推进到了下一段。")
    battle["waveIndex"] += 1
    battle["breakTurns"] = 0
    battle["vulnerability"] *= 0.78
    battle["dotPool"] *= 0.7

    if battle["waveIndex"] >= len(battle["waves"]):
        battle["cleared"] = True
        return

    next_wave = battle["waves"][battle["waveIndex"]]
    enemy_actor = _enemy_actor(battle)
    enemy_actor["speed"] = next_wave["speed"]
    enemy_actor["next"] = battle["currentTime"] + 44.0
    _log_event(battle, f"{next_wave['name']} 入场，目标数 {next_wave['remainingTargets']}。")


def _spawn_summon_if_needed(battle: dict[str, Any], wave: dict[str, Any], rng: random.Random) -> None:
    if float(wave.get("summonChance", 0.0)) <= 0:
        return
    if wave["remainingTargets"] >= int(wave.get("summonTargetsMax", wave["baseTargets"])):
        return
    if rng.random() >= float(wave.get("summonChance", 0.0)):
        return

    _spawn_specific_summons(
        battle,
        wave,
        1,
        summon_hp=float(wave.get("summonHp", wave["unitHp"] * 0.6)),
        pressure=float(wave.get("summonAttackPressure", wave.get("summonPressure", 0.0))),
    )


def _summarize_half(battle: dict[str, Any], half: dict[str, Any], mode: str) -> dict[str, Any]:
    cycle_equivalent = round(battle["currentTime"] / 260.0, 1)
    durability_ratio = round(max(0.0, min(battle["durability"] / battle["durabilityCap"], 1.0)), 2)
    phase_transitions = sum(int(wave.get("phaseIndex", 0)) for wave in battle["waves"])

    if battle["goal"] == "points":
        point_ratio = battle["scorePoints"] / max(battle["goalScore"], 1.0)
        battle["cleared"] = battle["scorePoints"] >= battle["goalScore"]
        score = 24.0 + min(point_ratio, 1.3) * 30.0
        score += min(10.0, battle["killCount"] * 0.32 + battle["breaks"] * 0.65)
        score += durability_ratio * 10.0
        score -= battle["enemyTurns"] * 0.35
        risk = _points_risk_label(battle["cleared"], point_ratio, durability_ratio)
        special_metric = {"label": "模拟积分", "value": int(round(battle["scorePoints"]))}
    else:
        tempo_score = 76.0 - cycle_equivalent * 8.8 - battle["enemyTurns"] * 1.1
        break_bonus = min(14.0, battle["breaks"] * 2.6)
        durability_bonus = durability_ratio * 18.0
        clear_bonus = 10.0 if battle["cleared"] else -18.0
        score = tempo_score + break_bonus + durability_bonus + clear_bonus
        risk = _risk_label(battle["cleared"], durability_ratio, cycle_equivalent)
        special_metric = None

    score = max(0.0, min(100.0, round(score, 1)))

    return {
        "half": half["name"],
        "cleared": battle["cleared"],
        "score": score,
        "cycleEquivalent": cycle_equivalent,
        "allyTurns": battle["allyTurns"],
        "enemyTurns": battle["enemyTurns"],
        "breaks": battle["breaks"],
        "durabilityRatio": durability_ratio,
        "riskLabel": risk,
        "interruptsUsed": battle["interruptsUsed"],
        "dangerousSkillsSeen": battle["dangerousSkillsSeen"],
        "phaseTransitions": phase_transitions,
        "specialMetric": special_metric,
        "log": battle["log"][:8],
    }


def _make_wave(
    *,
    name: str,
    archetype: str,
    targets: int,
    hp_per_target: float,
    toughness: float,
    speed: float,
    pressure: float,
    kill_score: float,
    respawns_remaining: int,
    respawn_scale: float,
    summon_chance: float,
    summon_targets_max: int,
    summon_hp: float,
    summon_attack_pressure: float,
    berserk_at: float,
    dangerous_skill: dict[str, Any] | None = None,
    phase_transitions: list[dict[str, Any]] | None = None,
    clear_summons_on_main_death: bool | None = None,
) -> dict[str, Any]:
    danger = dict(dangerous_skill or {})
    danger_start = 999
    if danger:
        danger_start = max(1, int(danger.get("firstAt", danger.get("cycle", 3))))

    if clear_summons_on_main_death is None:
        clear_summons_on_main_death = archetype in {"boss", "elite", "elite_summon"}

    return {
        "name": name,
        "archetype": archetype,
        "targets": targets,
        "baseTargets": targets,
        "mainTargetsAlive": targets,
        "remainingTargets": targets,
        "unitHp": hp_per_target,
        "hp": hp_per_target * targets,
        "toughness": toughness,
        "maxToughness": toughness,
        "speed": speed,
        "baseSpeed": speed,
        "pressure": pressure,
        "basePressure": pressure,
        "killScore": kill_score,
        "respawnsRemaining": respawns_remaining,
        "respawnsUsed": 0,
        "respawnScale": respawn_scale,
        "summonChance": summon_chance,
        "summonTargetsMax": summon_targets_max,
        "summonCount": 0,
        "summonHp": summon_hp,
        "summonAttackPressure": summon_attack_pressure,
        "berserkAt": berserk_at,
        "dangerousSkill": danger,
        "dangerStartTurns": danger_start,
        "dangerTurnsUntilTrigger": danger_start,
        "dangerChargeRemaining": 0,
        "phaseTransitions": list(phase_transitions or []),
        "phaseIndex": 0,
        "enemyTurnCounter": 0,
        "clearSummonsOnMainDeath": clear_summons_on_main_death,
    }


def _derive_waves(half: dict[str, Any], mode: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    if profile.get("waves"):
        waves = []
        for index, item in enumerate(profile["waves"], start=1):
            targets = int(item.get("targets", 1))
            hp_per_target = float(item.get("hpPerTarget", 90.0))
            toughness = float(item.get("toughness", 24.0))
            waves.append(
                _make_wave(
                    name=item.get("name", f"{half['name']} 第 {index} 波"),
                    archetype=item.get("archetype", "elite"),
                    targets=targets,
                    hp_per_target=hp_per_target,
                    toughness=toughness,
                    speed=float(item.get("speed", 100.0)),
                    pressure=float(item.get("pressure", 10.0)),
                    kill_score=float(item.get("killScore", 100.0)),
                    respawns_remaining=int(item.get("respawns", 0)),
                    respawn_scale=float(item.get("respawnScale", 1.08)),
                    summon_chance=float(item.get("summonChance", 0.0)),
                    summon_targets_max=int(item.get("summonTargetsMax", max(targets, targets + 1))),
                    summon_hp=float(item.get("summonHp", hp_per_target * 0.6)),
                    summon_attack_pressure=float(item.get("summonAttackPressure", item.get("summonPressure", 0.0))),
                    berserk_at=float(item.get("berserkAt", 0.0)),
                    dangerous_skill=item.get("dangerousSkill"),
                    phase_transitions=item.get("phaseTransitions"),
                    clear_summons_on_main_death=item.get("clearSummonsOnMainDeath"),
                )
            )
        return waves

    aoe_weight = float(half["weights"].get("aoe", 0.0))
    single_weight = float(half["weights"].get("single", 0.0))
    break_target = float(half["targets"].get("break", 10.0))
    survival_target = float(half["targets"].get("survival", 10.0))
    speed_target = float(half["targets"].get("speed", 10.0))

    if mode == "pure_fiction":
        target_pattern = [5, 4]
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
        unit_hp = 85.0 + sum(float(value) for value in half["targets"].values()) * 1.2
        if mode == "pure_fiction":
            unit_hp *= 0.55
        elif targets <= 1:
            unit_hp *= 1.8
        toughness = 18.0 + break_target * (1.12 if targets <= 2 else 0.8)
        speed = 96.0 + speed_target * 1.2 + (index - 1) * 4.0
        pressure = 6.5 + survival_target * 0.85 + targets * 0.7
        waves.append(
            _make_wave(
                name=f"{half['name']} 第 {index} 波",
                archetype="boss" if targets == 1 else "elite",
                targets=targets,
                hp_per_target=unit_hp,
                toughness=toughness,
                speed=speed,
                pressure=pressure,
                kill_score=100.0,
                respawns_remaining=0,
                respawn_scale=1.08,
                summon_chance=0.0,
                summon_targets_max=targets,
                summon_hp=unit_hp * 0.6,
                summon_attack_pressure=0.0,
                berserk_at=0.0,
            )
        )
    return waves


def _choose_action(unit: dict[str, Any], battle: dict[str, Any]) -> str:
    roles = set(unit["base"]["roles"])
    uid = unit["id"]
    energy = battle["energy"][uid]
    if energy >= 100.0:
        return "ultimate"
    if uid == "sparkle" and battle["sp"] <= 1:
        return "skill"
    if uid == "robin" and battle["allyTurns"] >= 2 and battle["sp"] > 0:
        return "skill"
    if uid == "trailblazer_harmony" and battle["sp"] > 0:
        return "skill"
    if uid == "gallagher" and (battle["breakTurns"] > 0 or battle["sp"] > 2):
        return "skill"
    if "support" in roles:
        if battle["sp"] > 0 and (_effect_total(battle, "damage") < 0.14 or battle["allyTurns"] < 3):
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


def _team_flags(team: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {unit["id"] for unit in team}
    nihility_count = sum(1 for unit in team if unit["base"].get("path") == "虚无")
    fua_sum = sum(unit["effective_traits"].get("fua", 0.0) for unit in team)
    return {
        "ids": ids,
        "dot_core": {"kafka", "black_swan"}.issubset(ids),
        "super_break_core": {"firefly", "trailblazer_harmony"}.issubset(ids),
        "himeko_herta": {"himeko", "herta"}.issubset(ids),
        "ratio_topaz": {"dr_ratio", "topaz"}.issubset(ids),
        "acheron_core": "acheron" in ids and nihility_count >= 2,
        "fua_core": fua_sum >= 18.0 or {"dr_ratio", "topaz"}.issubset(ids) or {"himeko", "herta"}.issubset(ids),
        "aventurine": "aventurine" in ids,
    }


def _primary_carry_id(team: list[dict[str, Any]]) -> str | None:
    weighted = []
    for unit in team:
        roles = set(unit["base"]["roles"])
        if "main_dps" not in roles and "sub_dps" not in roles:
            continue
        score = (
            unit["effective_traits"].get("single", 0.0)
            + unit["effective_traits"].get("aoe", 0.0)
            + unit["effective_traits"].get("break", 0.0) * 0.7
            + unit["effective_traits"].get("fua", 0.0) * 0.6
            + unit["investment"] / 10.0
        )
        if "main_dps" in roles:
            score += 6.0
        weighted.append((score, unit["id"]))
    if not weighted:
        return None
    weighted.sort(reverse=True)
    return weighted[0][1]


def _profile_damage_bonus(buffs: dict[str, Any], traits: dict[str, float], wave: dict[str, Any]) -> float:
    bonus = 0.0
    if wave["remainingTargets"] >= 3:
        bonus += float(buffs.get("aoeBonus", 0.0))
    if wave["remainingTargets"] <= 2:
        bonus += float(buffs.get("singleBonus", 0.0))
    if traits.get("debuff", 0.0) >= 5.0:
        bonus += float(buffs.get("debuffBonus", 0.0))
    if traits.get("dot", 0.0) >= 5.0:
        bonus += float(buffs.get("dotBonus", 0.0))
    if traits.get("fua", 0.0) >= 5.0:
        bonus += float(buffs.get("fuaBonus", 0.0))
    return bonus


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
        bonus += 2.4
    if "sustain" in roles:
        bonus += 1.8
    if "main_dps" in roles:
        bonus += 1.2
    return 92.0 + unit["effective_traits"].get("speed", 0.0) * 3.9 + unit["investment"] * 0.18 + bonus


def _role_factor(unit: dict[str, Any]) -> float:
    roles = set(unit["base"]["roles"])
    if "main_dps" in roles:
        return 1.2
    if "sub_dps" in roles:
        return 1.06
    if "support" in roles:
        return 0.72
    if "sustain" in roles:
        return 0.44
    return 1.0


def _effect_total(battle: dict[str, Any], effect_type: str) -> float:
    return round(
        sum(effect["value"] for effect in battle["effects"] if effect["type"] == effect_type and effect["remaining"] > 0),
        4,
    )


def _apply_effect(
    battle: dict[str, Any],
    effect_type: str,
    value: float,
    remaining: int,
    tick: str,
) -> None:
    battle["effects"].append(
        {
            "type": effect_type,
            "value": round(float(value), 4),
            "remaining": int(remaining),
            "tick": tick,
        }
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


def _advance_actor(battle: dict[str, Any], actor_id: str, percent: float) -> None:
    for actor in battle["actors"]:
        if actor["id"] == actor_id:
            actor["next"] = max(battle["currentTime"] + 1.0, actor["next"] * max(0.1, 1.0 - percent))
            return


def _advance_allies(battle: dict[str, Any], percent: float, *, exclude_id: str | None = None) -> None:
    for actor in battle["actors"]:
        if actor["kind"] != "ally":
            continue
        if exclude_id and actor["id"] == exclude_id:
            continue
        actor["next"] = max(battle["currentTime"] + 1.0, actor["next"] * max(0.1, 1.0 - percent))


def _action_delay(speed: float, speed_bonus: float) -> float:
    effective_speed = max(82.0, speed * (1.0 + speed_bonus))
    return round(10000.0 / effective_speed, 2)


def _initial_delay(speed: float, rng: random.Random, *, ally: bool) -> float:
    base = 10000.0 / speed
    if ally:
        return round(base * (0.72 + rng.random() * 0.16), 2)
    return round(base * (0.8 + rng.random() * 0.14), 2)


def _alive_hp_capacity(wave: dict[str, Any]) -> float:
    main_hp = max(0, int(wave.get("mainTargetsAlive", wave.get("remainingTargets", 0)))) * float(wave["unitHp"])
    summon_hp = max(0, int(wave.get("summonCount", 0))) * float(wave.get("summonHp", wave["unitHp"] * 0.6))
    return max(main_hp + summon_hp, 0.0)


def _next_defeated_target(wave: dict[str, Any]) -> dict[str, Any] | None:
    summon_count = int(wave.get("summonCount", 0))
    main_targets = int(wave.get("mainTargetsAlive", wave.get("remainingTargets", 0)))
    summon_hp = float(wave.get("summonHp", wave["unitHp"] * 0.6))
    main_hp = float(wave["unitHp"])
    if summon_count > 0 and (main_targets <= 0 or summon_hp <= main_hp):
        return {"kind": "summon", "hp": summon_hp}
    if main_targets > 0:
        return {"kind": "main", "hp": main_hp}
    if summon_count > 0:
        return {"kind": "summon", "hp": summon_hp}
    return None


def _wave_hp_ratio(wave: dict[str, Any]) -> float:
    max_hp = max(_alive_hp_capacity(wave), 1.0)
    return max(0.0, min(wave["hp"] / max_hp, 1.0))


def _risk_label(cleared: bool, durability_ratio: float, cycle_equivalent: float) -> str:
    if not cleared:
        return "容易翻车"
    if durability_ratio >= 0.55 and cycle_equivalent <= 5.0:
        return "稳定"
    if durability_ratio >= 0.35 and cycle_equivalent <= 6.0:
        return "可接受"
    return "偏冒险"


def _points_risk_label(cleared: bool, point_ratio: float, durability_ratio: float) -> str:
    if point_ratio >= 1.05 and durability_ratio >= 0.35:
        return "稳定"
    if cleared or point_ratio >= 0.85:
        return "可接受"
    return "容易翻车"


def _build_simulation_notes(mode: str, pair_clear_rate: float, top_clear_rate: float, bottom_clear_rate: float) -> list[str]:
    notes = []
    if mode == "pure_fiction":
        if pair_clear_rate >= 0.7:
            notes.append("这套双队在刷分模拟里比较稳定，常规随机下也更容易接近目标积分。")
        elif pair_clear_rate >= 0.45:
            notes.append("这套双队能刷出不错成绩，但对出手顺序和连锁击杀比较敏感。")
        else:
            notes.append("这套双队刷分上限不差，但平均表现波动偏大。")
    else:
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


def _select_key_moments(log: list[str], limit: int = 5) -> list[str]:
    if len(log) <= limit:
        return log

    keywords = ("插入终结技", "危险技能", "蓄力", "召出", "阶段", "狂暴", "破韧窗口")
    picked: list[str] = []
    seen: set[str] = set()

    for keyword in keywords:
        for item in log:
            if keyword in item and item not in seen:
                picked.append(item)
                seen.add(item)
                if len(picked) >= limit:
                    return picked

    for item in log:
        if item in seen:
            continue
        picked.append(item)
        seen.add(item)
        if len(picked) >= limit:
            break

    return picked


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
    if len(battle["log"]) < 16 and message not in battle["log"]:
        battle["log"].append(message)
