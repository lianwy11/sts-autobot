# -*- coding: utf-8 -*-
# Slay the Spire driver v3 for CommunicationMod.
# One decision per state line; the mod re-sends state after every command.
import sys, json, os, io, time, glob
from collections import deque

BASE = os.path.dirname(os.path.abspath(__file__))
MANUAL = os.path.join(BASE, "manual_cmd.txt")
MODE = os.path.join(BASE, "mode.txt")
LOG = os.path.join(BASE, "driver_log.txt")
LAST = os.path.join(BASE, "last_state.json")

RESUME_CLICK = "CLICK LEFT 240 660"

RAW_IN = sys.stdin.buffer
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

def decode_in(raw):
    """Mod writes JSON with the platform default charset (GBK on zh-CN
    Windows); try UTF-8 first, then GBK, so Chinese names survive intact."""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

# ---------------- card knowledge ----------------
# (damage, hits, block, tag)  tag: weak/vuln/poison/energy/buff
CARD_DB = {
    "Strike_R": (6, 1, 0, ""), "Bash": (8, 1, 0, "vuln"),
    "Defend_R": (0, 1, 5, ""), "Headbutt": (9, 1, 0, ""),
    "Twin Strike": (5, 2, 0, ""), "Pommel Strike": (9, 1, 0, ""),
    "Anger": (6, 1, 0, ""), "Clothesline": (12, 1, 0, "weak"),
    "Iron Wave": (5, 1, 5, ""), "Flex": (0, 1, 0, "buff"),
    "Uppercut": (13, 1, 0, "weak"), "Searing Blow": (12, 1, 0, ""),
    "Whirlwind": (5, 3, 0, ""), "Metallicize": (0, 1, 0, "buff"),
    "Inflame": (0, 1, 0, "buff"), "Shrug It Off": (0, 1, 8, ""),
    "True Grit": (0, 1, 7, ""), "Armaments": (0, 1, 5, ""),
    "Carnage": (20, 1, 0, ""), "Heavy Blade": (14, 1, 0, ""),
    "Feed": (10, 1, 0, ""), "Impervious": (0, 1, 30, ""),
    "Reaper": (4, 1, 0, ""), "Offering": (0, 1, 0, "energy"),
    "Strike_G": (6, 1, 0, ""), "Defend_G": (0, 1, 5, ""),
    "Neutralize": (3, 1, 0, "weak"), "Survivor": (0, 1, 8, ""),
    "Slice": (6, 1, 0, ""), "Cloak and Dagger": (6, 1, 0, ""),
    "Dagger Throw": (9, 1, 0, ""), "Deadly Poison": (0, 1, 0, "poison"),
    "Poisoned Stab": (6, 1, 0, "poison"), "Quick Slash": (8, 1, 0, ""),
    "Blade Dance": (8, 1, 0, ""), "Backflip": (7, 1, 5, ""),
    "Sneaky Strike": (12, 1, 0, ""), "Predator": (15, 1, 0, ""),
    "Terror": (0, 1, 0, "vuln"), "Footwork": (0, 1, 0, "buff"),
    "Backstab": (11, 1, 0, ""), "Prepared": (0, 1, 0, ""),
    "Sucker Punch": (7, 1, 0, "weak"), "Eviscerate": (7, 3, 0, ""),
    "Bouncing Blade": (3, 3, 0, ""), "Outmaneuver": (0, 1, 0, "energy"),
    "Leg Sweep": (0, 1, 11, "weak"), "Heel Hook": (5, 1, 0, ""),
    "Acrobatics": (0, 1, 0, ""), "Caltrops": (0, 1, 0, "buff"),
    "Noxious Fumes": (0, 1, 0, "buff"), "Well Laid Plans": (0, 1, 0, "buff"),
    "Adrenaline": (0, 1, 0, "buff"), "Burst": (0, 1, 0, "buff"),
    "Corpse Explosion": (0, 1, 0, "poison"), "Die Die Die": (13, 1, 0, ""),
    "Wraith Form": (0, 1, 0, "buff"), "A Thousand Cuts": (0, 1, 0, "buff"),
    "Dagger Spray": (4, 2, 0, ""), "All-Out Attack": (10, 1, 0, ""),
    "Finisher": (5, 1, 0, ""), "Expertise": (0, 1, 0, ""),
    "Bouncing Flask": (0, 1, 0, "poison"), "Catalyst": (0, 1, 0, "poison"),
    "Envenom": (0, 1, 0, "buff"), "After Image": (0, 1, 0, "buff"),
}

# Card reward tiers by id (higher = want more). Missing = 1.
CARD_TIER = {
    # Silent
    "Terror": 3, "Adrenaline": 3, "Corpse Explosion": 3, "Noxious Fumes": 3,
    "Wraith Form": 3, "Well Laid Plans": 3, "A Thousand Cuts": 3, "Burst": 3,
    "Die Die Die": 3, "After Image": 3, "Envenom": 3, "Footwork": 3,
    "Predator": 3, "Backstab": 3, "Blade Dance": 2.5, "Bouncing Flask": 3,
    "Caltrops": 2.5, "Deadly Poison": 2.5, "Poisoned Stab": 2.5, "Backflip": 2.5,
    "Sucker Punch": 2.5, "Eviscerate": 2.5, "Dagger Spray": 2, "Leg Sweep": 2.5,
    "Quick Slash": 2, "Dagger Throw": 2, "Slice": 1.5, "Sneaky Strike": 2,
    "Heel Hook": 2, "All-Out Attack": 2, "Finisher": 2, "Acrobatics": 1.5,
    "Prepared": 1, "Outmaneuver": 1.5, "Expertise": 1.5, "Setup": 0.5,
    "Reflex": 0.5, "Endless Agony": 1.5,
    # Ironclad
    "Feed": 3, "Immolate": 3, "Demon Form": 3, "Barricade": 3, "Reaper": 3,
    "Impervious": 3, "Offering": 2.5, "Uppercut": 3, "Metallicize": 2.5,
    "Inflame": 2.5, "Whirlwind": 2.5, "Heavy Blade": 2.5, "Carnage": 2.5,
    "Shrug It Off": 2.5, "Headbutt": 1.5, "Twin Strike": 2, "Pommel Strike": 2,
    "Searing Blow": 2, "Clothesline": 2, "Iron Wave": 1.5, "Anger": 1.5,
    "True Grit": 1.5, "Armaments": 2, "Flex": 1.5, "Battle Trance": 2,
    "Bloodletting": 2, "Spot Weakness": 2, "Thunderclap": 2,
    "Dark Embrace": 2.5, "Corruption": 3, "Feel No Pain": 2.5,
    "Second Wind": 2.5, "Juggernaut": 2.5, "Shockwave": 2.5,
    "Intimidate": 1.5, "Fire Breathing": 1.5, "Rampage": 2.5,
    "Infernal Blade": 2, "Warcry": 1.5, "Ghostly Armor": 2,
    # damage engines: the act-1 boss demands ~20+ dmg/turn, these get there
    "Bash": 2.5, "Inflame": 3.5, "Spot Weakness": 3, "Demon Form": 3.5,
    "Rupture": 2.5, "Brutality": 2.5, "Heavy Blade": 3, "Whirlwind": 3,
    "Limit Break": 3.5, "Barricade": 3, "Berserk": 2.5,
}
UPGRADE_PRIORITY = [
    "Bash", "Inflame", "Spot Weakness", "Demon Form", "Limit Break",
    "Feed", "Immolate", "Uppercut", "Predator", "Blade Dance", "Footwork",
    "Metallicize", "Inflame", "Deadly Poison", "Noxious Fumes", "Terror",
    "Carnage", "Heavy Blade", "Whirlwind", "Backstab", "Poisoned Stab",
    "Impervious", "Juggernaut", "Second Wind", "Shockwave", "Dark Embrace",
    "Shrug It Off", "Spot Weakness", "Thunderclap", "Leg Sweep",
    "Strike_R", "Strike_G", "Neutralize",
    "Twin Strike", "Pommel Strike", "Defend_R", "Defend_G",
]
REMOVE_PRIORITY = ["Regret", "Injury", "Clumsy", "Decay", "Doubt", "Shame",
                    "Normality", "Pain", "Void",
                    "Strike_G", "Strike_R", "Survivor", "Defend_G", "Defend_R"]

# ---------------- archetype synergy ----------------
STR_GAIN = {"Inflame", "Spot Weakness", "Feed", "Flex", "Demon Form", "Rupture"}
MULTIHIT = {"Whirlwind", "Twin Strike", "Pommel Strike", "Sword Boomerang",
            "Heavy Blade", "Skewer", "Searing Blow", "Thunderclap"}
BLOCK_CORE = {"Metallicize", "Barricade", "Shrug It Off", "Impervious", "Body Slam"}
POISON_CORE = {"Deadly Poison", "Poisoned Stab", "Noxious Fumes", "Bouncing Flask",
               "Catalyst", "Corpse Explosion"}
SHIV_CORE = {"Blade Dance", "Cloak and Dagger", "Infinite Blades", "Dead Branch",
             "Storm of Steel"}
SHIV_PAYOFF = {"After Image", "A Thousand Cuts", "Envenom", "Finisher"}
DEX_CORE = {"Footwork", "Backflip", "Leg Sweep"}

def synergy_bonus(card_id, deck_ids):
    """Score bump from the deck the card would join (build-around logic)."""
    b = 0.0
    def n(pool):
        return sum(1 for c in deck_ids if c in pool)
    if card_id in STR_GAIN and n(MULTIHIT) >= 2:
        b += 1.5
    if card_id in MULTIHIT and n(STR_GAIN) >= 2:
        b += 1.5
    if card_id in BLOCK_CORE:
        if n(BLOCK_CORE) >= 2:
            b += 1.0
        if card_id == "Body Slam" and n({"Barricade", "Metallicize"}) >= 1:
            b += 2.0
    if card_id in POISON_CORE:
        p = n(POISON_CORE)
        if p >= 1:
            b += 1.0
        if p >= 2:
            b += 0.5
        if card_id == "Catalyst" and p >= 2:
            b += 1.5
    if card_id in SHIV_CORE and n(SHIV_CORE) >= 2:
        b += 1.0
    if card_id in SHIV_PAYOFF and n(SHIV_CORE) >= 3:
        b += 1.5
    if card_id in DEX_CORE and n(DEX_CORE) >= 2:
        b += 0.5
    EXHAUST_CORE = {"Corruption", "Feel No Pain", "Dark Embrace", "Second Wind"}
    if card_id in EXHAUST_CORE and n(EXHAUST_CORE) >= 1:
        b += 1.0
    return b

BAD_RELICS = set()  # buy nothing known-harmful; relic pool is mostly good

REGEN_RELICS = {"Burning Blood", "Magic Flower", "Black Blood"}  # sustain lowers rest value
POTION_BAN_RELICS = {"Sozu"}  # cannot drink potions at all
STAT_ATTACK_RELICS = {"Shuriken", "Kunai"}  # every 3 attacks -> str/dex

def relic_id_list(g):
    return [r.get("id") for r in (g.get("relics") or [])]

BOSS_AOE = {"Whirlwind", "Thunderclap", "Cleave", "Immolate", "Fire Breathing",
            "Dagger Spray", "All-Out Attack", "Corpse Explosion", "Die Die Die"}
BOSS_BLOCK = {"Metallicize", "Shrug It Off", "Impervious", "Footwork",
              "Ghostly Armor", "Barricade", "Juggernaut", "Second Wind"}

def boss_syn(card_id, boss):
    """Act boss is known from floor 1 (state.act_boss); bias the draft."""
    b = 0.0
    if boss == "Slime Boss":
        if card_id in BOSS_AOE:
            b += 0.75
    elif boss == "Hexaghost":
        if card_id in BOSS_BLOCK:
            b += 0.5
    elif boss == "The Guardian":
        if card_id in BOSS_BLOCK or card_id in STR_GAIN or card_id in MULTIHIT:
            b += 0.5
    return b


def relic_syn(card_id, relics):
    b = 0.0
    if card_id in SHIV_CORE or card_id in SHIV_PAYOFF:
        if "Shuriken" in relics or "Kunai" in relics:
            b += 0.75
    if card_id in MULTIHIT and "Pen Nib" in relics:
        b += 0.5
    if card_id in POISON_CORE and "Snecko Skull" in relics:
        b += 0.75
    if card_id in STR_GAIN and "Girya" in relics:
        b += 0.5
    return b

# Unified potion catalog: every potion as a value source, evaluated per turn.
POTION_CATALOG = {
    "FirePotion":          {"dmg": 20, "target": True},
    "ExplosivePotion":     {"dmg": 10, "aoe": True},
    "PoisonPotion":        {"poison": 4, "target": True},
    "EnergyPotion":        {"energy": 2},
    "StrengthPotion":      {"str": 2},
    "SteroidPotion":       {"str": 2, "temp": True},
    "DexterityPotion":     {"dex": 2},
    "SpeedPotion":         {"dex": 2, "temp": True},
    "SwiftPotion":         {"draw": 3},
    "SneckoOil":           {"draw": 5},
    "AttackPotion":        {"random_card": "ATTACK"},
    "SkillPotion":         {"random_card": "SKILL"},
    "PowerPotion":         {"random_card": "POWER"},
    "BlockPotion":         {"block": 12},
    "GhostinaJar":       {"intangible": 1},
    "EssenceofSteel":     {"plated": 2},
    "RegenPotion":         {"heal": 5, "regen": 3},
    "BloodPotion":         {"heal_pct": 0.25},
    "FruitJuice":          {"maxhp": 5},
    "FearPotion":          {"weak": 3, "target": True},
    "WeakPotion":          {"weak": 3, "target": True},
    "CultistPotion":       {"ritual": 1},
    "HeartofIron":        {"metallicize": 3},
    "CunningPotion":       {"shiv": 3},
    "DuplicationPotion":   {"dup": True},
    "BlessingoftheForge": {"upgrade_hand": True},
    "LiquidBronze":        {"thorns": 3},
    "SmokeBomb":           {"escape": True},
    "EntropicBrew":        {"brew": True},
    # Fairy in a Bottle (auto-revive) and Milk (dead card) are never drunk.
}

def out(line):
    try:
        sys.stdout.write(line.strip() + "\n")
        sys.stdout.flush()
    except OSError:
        # 游戏进程已消失（管道断裂）：驱动无事可做，干净退出
        log("stdout closed (game process gone); driver exiting")
        raise SystemExit(0)

def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass

def gs(state):
    return state.get("game_state") or {}

def scr(state):
    return gs(state).get("screen_state") or {}

def screen_type(state):
    g = gs(state)
    return (g.get("screen_type") or g.get("screen") or "").upper()

def choices(state):
    c = scr(state).get("choices")
    if isinstance(c, list) and c:
        return c
    c2 = gs(state).get("choice_list")
    return c2 if isinstance(c2, list) else []

def at_main_menu(state, avail_u):
    return "start" in avail_u and not state.get("in_game")

def power_amount(entry_list, pid):
    for p in entry_list or []:
        if isinstance(p, dict) and p.get("id") == pid:
            return p.get("amount") or 0
    return 0

def has_power(entry_list, *pids):
    for p in entry_list or []:
        if isinstance(p, dict) and p.get("id") in pids:
            return True
    return False

def card_info(card):
    cid = card.get("id") or ""
    base = CARD_DB.get(cid)
    if base:
        return base
    t = (card.get("type") or "").lower()
    name = card.get("name") or ""
    if "attack" in t:
        return (6, 1, 0, "")
    if any(k in name for k in ("防御", "格挡")):
        return (0, 1, 5, "")
    return (0, 1, 0, "")

def alive_monsters(combat):
    res = []
    for ri, m in enumerate(combat.get("monsters") or []):
        if (m.get("current_hp") or 0) > 0 and not m.get("is_gone") and not m.get("half_dead"):
            res.append((ri, m))
    return res

def monster_intent_damage(m):
    intent = (m.get("intent") or "").upper()
    if "ATTACK" not in intent:
        return 0
    dmg = max(m.get("move_adjusted_damage") or 0, m.get("move_base_damage") or 0)
    hits = m.get("move_hits") or 1
    total = dmg * max(hits, 1)
    if has_power(m.get("powers"), "Weak", "Shackled"):
        total = int(total * 0.75)
    return total

def estimated_attack(card, player):
    dmg, hits, blk, tag = card_info(card)
    if dmg <= 0:
        return 0
    strn = power_amount(player.get("powers"), "Strength")
    dmg += strn
    if has_power(player.get("powers"), "Weak"):
        dmg = int(dmg * 0.75)
    return dmg * hits

def estimated_block(card, player):
    dmg, hits, blk, tag = card_info(card)
    if blk <= 0:
        return 0
    b = blk + power_amount(player.get("powers"), "Dexterity")
    if has_power(player.get("powers"), "Frail"):
        b = int(b * 0.75)
    return b

def is_elite_or_boss(g):
    room = (g.get("room_type") or "").upper()
    return "ELITE" in room or "BOSS" in room

def potion_decision(state, g, player, mons, incoming, residual, hp_frac, attacks):
    """Unified potion valuation: score every held potion in HP-equivalent
    value for the current combat state; drink the best if it clears the bar."""
    combat = g.get("combat_state") or {}
    hand = combat.get("hand") or []
    room = (g.get("room_type") or "").upper()
    room_u = room
    max_hp = player.get("max_hp") or g.get("max_hp") or 1
    hp = player.get("current_hp") or g.get("current_hp") or 1
    missing = max_hp - hp
    energy = player.get("energy") or 3
    relics = set(relic_id_list(g))
    mon_eff_max = max(((m.get("current_hp") or 0) + (m.get("block") or 0)) for _, m in mons) if mons else 0
    total_atk = sum(estimated_attack(c, player) for _, c in attacks)
    est_turns = max(2, int(mon_eff_max / max(6, total_atk)) + 1)
    affordable_atk = 0
    budget = energy
    for _, c in sorted(attacks, key=lambda p: (p[1].get("cost") if isinstance(p[1].get("cost"), int) else 1)):
        cost = c.get("cost") if isinstance(c.get("cost"), int) else 1
        cost = max(0, cost)
        if cost <= budget:
            budget -= cost
            affordable_atk += 1

    # easy trash fights don't deserve resources: raise the bar
    big_fight = is_elite_or_boss(g)
    easy_fight = (not big_fight and len(mons) == 1
                  and mon_eff_max <= 40)
    cands = []
    for pi, p in enumerate(g.get("potions") or []):
        pid = p.get("id") or ""
        spec = POTION_CATALOG.get(pid.replace(" ", ""))
        if not spec or not p.get("can_use"):
            continue
        score = 0.0
        reason = pid
        cmd = "POTION use %d" % pi
        if spec.get("dmg"):
            d = spec["dmg"]
            if spec.get("aoe"):
                val = sum(min(d, (m.get("current_hp") or 0) + (m.get("block") or 0)) for _, m in mons)
                if len(mons) >= 2:
                    score = val * 1.1
                    reason = "aoe chunk %d" % val
            else:
                best_kill = None
                for ri, m in mons:
                    m_eff = (m.get("current_hp") or 0) + (m.get("block") or 0)
                    if m_eff <= d:
                        gain = m_eff + monster_intent_damage(m) * 1.5
                        if best_kill is None or gain > best_kill[0]:
                            best_kill = (gain, ri)
                if best_kill:
                    score = best_kill[0]
                    cmd = "POTION use %d %d" % (pi, best_kill[1])
                    reason = "kill for %d" % best_kill[0]
                else:
                    tgt = max(mons, key=lambda rm: monster_intent_damage(rm[1]))
                    m_eff = (tgt[1].get("current_hp") or 0) + (tgt[1].get("block") or 0)
                    score = min(d, m_eff) * 0.9 + monster_intent_damage(tgt[1]) * 0.3
                    cmd = "POTION use %d %d" % (pi, tgt[0])
                    reason = "chip biggest threat"
        elif spec.get("weak"):
            tgt = max(mons, key=lambda rm: monster_intent_damage(rm[1]))
            if not has_power(tgt[1].get("powers"), "Weak") and monster_intent_damage(tgt[1]) >= 8:
                score = monster_intent_damage(tgt[1]) * 0.75 * min(3, est_turns)
                cmd = "POTION use %d %d" % (pi, tgt[0])
                reason = "weak the %d-dmg hitter" % monster_intent_damage(tgt[1])
        elif spec.get("str"):
            n = affordable_atk
            if any((c[1].get("id") == "Whirlwind") for c in attacks):
                n += 1  # whirlwind converts leftover energy into more hits
            if n >= 2 and (big_fight or hp_frac < 0.8 or est_turns >= 4):
                score = 2.2 * min(n, 5)
                reason = "+2 str with %d attacks queued" % n
        elif spec.get("dex"):
            blk_cards = sum(1 for c in hand
                            if "skill" in (c.get("type") or "").lower()
                            and c.get("is_playable"))
            if incoming >= 8 and blk_cards >= 1 and (big_fight or est_turns >= 3):
                score = 2.0 * min(3, blk_cards) + min(residual, 4)
                reason = "dex before %d blocks" % blk_cards
        elif spec.get("block"):
            if residual >= 8:
                score = min(residual, 12)
                reason = "block %d of %d residual" % (min(residual, 12), residual)
        elif spec.get("intangible"):
            if incoming >= 14:
                hits = sum((m.get("move_hits") or 1) for _, m in mons if monster_intent_damage(m) > 0)
                score = incoming - hits
                reason = "intangible vs %d incoming" % incoming
        elif spec.get("energy"):
            plays_cost = 0
            for c in hand:
                if c.get("is_playable"):
                    cost = c.get("cost") if isinstance(c.get("cost"), int) else 1
                    plays_cost += max(0, cost)
            if plays_cost >= energy + 1:
                score = min(8, plays_cost - energy + 3)
                reason = "+2 energy for a %d-cost hand" % plays_cost
        elif spec.get("draw"):
            playable_now = sum(1 for c in hand if c.get("is_playable"))
            if playable_now <= 1:
                score = 5
                reason = "out of gas, draw"
        elif spec.get("heal_pct"):
            heal = int(max_hp * spec["heal_pct"])
            if missing >= heal:
                score = heal
                reason = "heal %d" % heal
            elif missing >= heal * 0.5:
                score = heal * (0.8 if "BOSS" in room_u else 0.7)
                reason = "heal (partial) %d" % missing
        elif spec.get("heal"):
            total_h = spec["heal"] + spec.get("regen", 0) * 3
            if missing >= 8:
                score = min(missing, total_h) * 0.9
                reason = "regen ~%d over fight" % total_h
        elif spec.get("maxhp"):
            score = 5
            reason = "free +5 max hp"
        elif spec.get("ritual") or spec.get("metallicize") or spec.get("plated"):
            per = spec.get("ritual", 0) or spec.get("metallicize", 0) or spec.get("plated", 0)
            if est_turns >= 4:
                score = per * min(est_turns, 6) * 0.8
                reason = "sustain %d/turn for ~%d turns" % (per, est_turns)
        elif spec.get("poison"):
            if est_turns >= 3:
                score = spec["poison"] * 2.2
                tgt = max(mons, key=lambda rm: (rm[1].get("current_hp") or 0))
                cmd = "POTION use %d %d" % (pi, tgt[0])
                reason = "poison dot on the tank"
        elif spec.get("upgrade_hand"):
            unup = sum(1 for c in hand if (c.get("upgrades") or 0) == 0
                       and "attack" in (c.get("type") or "").lower())
            if unup >= 3:
                score = unup * 2.2
                reason = "forge %d attacks in hand" % unup
        elif spec.get("dup"):
            best_atk = max((estimated_attack(c, player) for _, c in attacks), default=0)
            if best_atk >= 10:
                score = best_atk * 0.8
                reason = "duplicate the %d-dmg card" % best_atk
        elif spec.get("shiv"):
            bonus = 2 if (relics & {"Shuriken", "Kunai"}) else 0
            score = 3 + bonus
            reason = "shiv fuel%s" % ("+stat relics" if bonus else "")
        elif spec.get("thorns"):
            if incoming >= 6 and est_turns >= 4:
                score = 6
                reason = "thorns grind"
        elif spec.get("random_card"):
            playable_now = sum(1 for c in hand if c.get("is_playable"))
            if playable_now <= 2 and est_turns >= 3:
                score = 4
                reason = "random card fuel"
        elif spec.get("escape"):
            if hp_frac <= 0.35 and "BOSS" not in room:
                score = 30
                reason = "smoke bomb saves a dying run"
        elif spec.get("brew"):
            held = sum(1 for q in (g.get("potions") or [])
                       if (q.get("id") or "") not in ("Potion Slot", ""))
            if held <= 1:
                score = 6
                reason = "reroll empty slots"
        if score > 0:
            cands.append((score, cmd, reason))

    if not cands:
        return None
    cands.sort(key=lambda t: -t[0])
    score, cmd, reason = cands[0]
    bar = 8 if easy_fight else (3 if "BOSS" in room_u else (4 if is_elite_or_boss(g) else 5))
    if hp_frac <= 0.3:
        bar = 0  # about to die: any potion that helps, now
    if (g.get("floor") or 0) >= 13 and "BOSS" not in room_u and not is_elite_or_boss(g):
        bar += 2  # pre-boss floors: hoard resources for the act boss
    if score >= bar:
        log("potion: %s (value %.0f, bar %d)" % (reason, score, bar))
        return cmd
    return None


def combat_action(state, avail_u):
    g = gs(state)
    combat = g.get("combat_state") or {}
    hand = combat.get("hand") or []
    player = combat.get("player") or {}
    mons = alive_monsters(combat)
    if not mons:
        return None

    incoming = sum(monster_intent_damage(m) for _, m in mons)
    hp = player.get("current_hp") or g.get("current_hp") or 1
    max_hp = player.get("max_hp") or g.get("max_hp") or 1
    hp_frac = hp / float(max_hp) if max_hp else 1.0
    cur_block = player.get("block") or 0
    residual = max(0, incoming - cur_block)
    big_fight = is_elite_or_boss(g)
    mon_hp_max = max((m.get("current_hp") or 0) + (m.get("block") or 0) for _, m in mons)

    playable = [(i, c) for i, c in enumerate(hand, 1) if c.get("is_playable")]
    attacks = [(i, c) for i, c in playable if "attack" in (c.get("type") or "").lower()]
    skills = [(i, c) for i, c in playable if "skill" in (c.get("type") or "").lower()]
    powers = [(i, c) for i, c in playable if "power" in (c.get("type") or "").lower()]
    potions = list(enumerate(g.get("potions") or []))

    def kill_target(min_dmg):
        cands = [(ri, m) for ri, m in mons
                 if (m.get("current_hp") or 0) + (m.get("block") or 0) <= min_dmg]
        if cands:
            return min(cands, key=lambda rm: (rm[1].get("current_hp") or 0))[0]
        return None

    # 0a. lethal by attacks: kill the weakest if all attacks together can
    total_atk = sum(estimated_attack(c, player) for _, c in attacks)
    ri = kill_target(total_atk)
    if ri is not None and attacks:
        best = max(attacks, key=lambda p: estimated_attack(p[1], player))
        return "PLAY %d %d" % (best[0], ri)

    # 0b. unified potion valuation (all potions, all contexts)
    if "Sozu" not in relic_id_list(g):
        pcmd = potion_decision(state, g, player, mons, incoming, residual,
                               hp_frac, attacks)
        if pcmd:
            return pcmd

    # 1c. boss fight: vulnerable uptime is a damage multiplier - apply first
    room_u2 = (g.get("room_type") or "").upper()
    if "BOSS" in room_u2 or "ELITE" in room_u2:
        tgt = max(mons, key=lambda rm: (rm[1].get("current_hp") or 0))[1]
        if not has_power(tgt.get("powers"), "Vulnerable"):
            vuln_cards = [(i, c) for i, c in skills + attacks
                          if card_info(c)[3] == "vuln"]
            big_hit = any(estimated_attack(c, player) >= 10 for _, c in attacks)
            if vuln_cards and (big_hit or hp_frac > 0.5):
                ri = [r for r, m in mons if m is tgt][0]
                return "PLAY %d %d" % (vuln_cards[0][0], ri)

    # 2. weaken big attackers (potions already handled by the evaluator)
    if incoming >= 10:
        threat = max(mons, key=lambda rm: monster_intent_damage(rm[1]))[1]
        if not has_power(threat.get("powers"), "Weak"):
            for i, c in skills + attacks:
                if card_info(c)[3] == "weak":
                    return "PLAY %d %d" % (i, [r for r, m in mons if m is threat][0])
        if not has_power(threat.get("powers"), "Vulnerable"):
            for i, c in skills + attacks:
                if card_info(c)[3] == "vuln":
                    return "PLAY %d %d" % (i, [r for r, m in mons if m is threat][0])

    # 2c. desperation: this turn's damage could kill us - all-in defense
    if hp <= incoming + 2 and hp_frac <= 0.5:
        blk_all = [(i, c, estimated_block(c, player)) for i, c in skills
                   if estimated_block(c, player) > 0]
        if blk_all:
            blk_all.sort(key=lambda t: -t[2])
            log("desperation: hp %d vs %d incoming -> block" % (hp, incoming))
            return "PLAY %d" % blk_all[0][0]

    # 3. block policy: bosses near-full block, elites/boss 4, else 6
    mon_ids = "|".join((m.get("id") or "") + (m.get("name") or "") for _, m in mons)
    if "GremlinNob" in mon_ids or "地精大汉" in mon_ids:
        threshold = 4  # enrage adds +2 str/skill, but unblocked 20-dmg turns kill
    elif "Lagavulin" in mon_ids and incoming > 0:
        threshold = 3  # awake Lagavulin: 18-20 per turn, must block
    elif "BOSS" in (g.get("room_type") or "").upper():
        threshold = 3
    elif big_fight or hp_frac < 0.5:
        threshold = 4
    else:
        threshold = 6
    if residual >= threshold:
        blk_cards = [(i, c, estimated_block(c, player)) for i, c in skills]
        blk_cards = [t for t in blk_cards if t[2] >= 3]
        if not blk_cards:
            # debuffed/weak blocks still save HP when the alternative is dying
            blk_cards = [(i, c, estimated_block(c, player)) for i, c in skills
                         if estimated_block(c, player) > 0]
        if blk_cards:
            blk_cards.sort(key=lambda t: -t[2])
            i, c, _ = blk_cards[0]
            return "PLAY %d" % i

    # 5. develop powers when safe
    if residual < threshold and powers:
        good = [(i, c) for i, c in powers if card_info(c)[3] in ("buff", "energy")]
        if good:
            return "PLAY %d" % good[0][0]

    # 6. poison on long fights; commit harder when the deck is a poison build
    deck_ids = [c.get("id") for c in (g.get("deck") or [])]
    poison_build = sum(1 for c in deck_ids if c in POISON_CORE) >= 3
    if mon_hp_max > (25 if poison_build else 40):
        for i, c in skills + attacks:
            if card_info(c)[3] == "poison":
                threat = max(mons, key=lambda rm: (rm[1].get("current_hp") or 0))
                return "PLAY %d %d" % (i, threat[0])

    # 7. biggest attack, avoid dumping into heavy block; AOE first vs split boss
    if attacks:
        if (g.get("act_boss") or "") == "Slime Boss" and len(mons) >= 2:
            aoe = [p for p in attacks if (p[1].get("id") or "") in BOSS_AOE]
            if aoe:
                i, c = aoe[0]
                return "PLAY %d 0" % i
        best = max(attacks, key=lambda p: (estimated_attack(p[1], player), -p[1].get("cost", 0)))
        dmg = estimated_attack(best[1], player)
        targets = [(ri, m) for ri, m in mons if (m.get("block") or 0) < dmg]
        pool = targets or mons
        killable = [(ri, m) for ri, m in pool
                    if (m.get("current_hp") or 0) + (m.get("block") or 0) <= dmg * 3]
        if killable:
            tgt = min(killable, key=lambda rm: (rm[1].get("current_hp") or 0) + (rm[1].get("block") or 0))[0]
        else:
            tgt = max(pool, key=lambda rm: monster_intent_damage(rm[1]))[0]
        return "PLAY %d %d" % (best[0], tgt)

    # 8. spare block
    if skills:
        blk_cards = [(i, c) for i, c in skills if estimated_block(c, player) >= 5]
        if blk_cards:
            return "PLAY %d" % blk_cards[0][0]

    return "END"

def card_reward_action(state, avail_u):
    g = gs(state)
    cards = scr(state).get("cards") or []
    deck = g.get("deck") or []
    deck_ids = [c.get("id") for c in deck]
    ch = choices(state)
    if not ch:
        return "RETURN"
    threshold = 2 if len(deck) >= 14 else 1.5
    # dilution guard: a big deck of 2.0-tier cards can't out-damage a boss
    BASIC = {"Strike_R", "Strike_G", "Defend_R", "Defend_G", "Strike_B", "Defend_B",
             "Strike_P", "Defend_P", "Bash", "Neutralize", "Survivor", "Eruption", "Vigilance"}
    mid_attacks = sum(1 for c in deck
                      if "attack" in (c.get("type") or "").lower()
                      and (c.get("id") or "") not in BASIC
                      and CARD_TIER.get(c.get("id") or "", 1) <= 2.0)
    if mid_attacks >= 4:
        threshold = max(threshold, 2.8)  # only real upgrades from here
    if len(deck) >= 20:
        threshold = max(threshold, 3.0)
    id_of = {}
    for c in cards:
        id_of[c.get("name")] = c.get("id")
    best_i, best_score = None, threshold
    for i, name in enumerate(ch):
        cid = id_of.get(name)
        if not cid:
            continue
        score = (CARD_TIER.get(cid, 1) + synergy_bonus(cid, deck_ids)
            + relic_syn(cid, relic_id_list(g)) + boss_syn(cid, g.get("act_boss") or ""))
        if score > best_score:
            best_i, best_score = i, score
    log("reward debug: ch=%s ids=%s thr=%.1f deck=%d" % (
        list(ch), [c.get("id") for c in cards], threshold, len(deck)))
    if best_i is not None:
        cid = id_of.get(ch[best_i]) or "?"
        log("card reward: take %s (tier %.1f + syn %.1f)" % (
            cid, CARD_TIER.get(cid, 1),
            best_score - CARD_TIER.get(cid, 1)))
        return "CHOOSE %d" % best_i
    log("card reward: skip all of %s" % [c.get("id") for c in cards])
    return "RETURN"

def grid_action(state, avail_u):
    # GRID = smith upgrade (RestRoom) or purge (shop/events)
    room = (gs(state).get("room_type") or "").upper()
    cards = scr(state).get("cards") or []
    ch = choices(state)
    if not ch:
        return "CHOOSE 0"
    prio = UPGRADE_PRIORITY if "REST" in room else REMOVE_PRIORITY
    def rank(c):
        cid = c.get("id") or ""
        if cid in prio:
            return prio.index(cid)
        return len(prio)
    if cards:
        best = min(cards, key=rank)
        for i, name in enumerate(ch):
            if name == best.get("name"):
                log("grid(%s): pick '%s'" % ("smith" if "REST" in room else "purge", best.get("id")))
                return "CHOOSE %d" % i
    return "CHOOSE 0"

def shop_action(state, avail_u, ctx):
    """Spend gold: purge bloat > relic deals > cards by tier+synergy > potions."""
    g = gs(state)
    gold = g.get("gold") or 0
    ss = scr(state)
    cards = ss.get("cards") or []
    relics = ss.get("relics") or []
    potions = ss.get("potions") or []
    purge_cost = ss.get("purge_cost") or 75
    ch = [str(c).lower() for c in choices(state)]  # card choices are lowercased by the mod
    if not ch:
        return "PROCEED"
    log("shop: gold=%d purge=%s(%s) cards=%s relics=%s potions=%s" % (
        gold, ss.get("purge_available"), purge_cost,
        [(c.get("id"), c.get("price")) for c in cards],
        [(r.get("id"), r.get("price")) for r in relics],
        [(p.get("id"), p.get("price")) for p in potions]))

    def buy(name, why):
        target = (name or "").lower()
        for i, n in enumerate(ch):
            if n == target:
                log("shop: BUY %s (%s) gold %d" % (name, why, gold))
                return "CHOOSE %d" % i
        return None

    deck = g.get("deck") or []
    deck_ids = [c.get("id") for c in deck]
    act = g.get("act") or 1
    relics_held = relic_id_list(g)

    # 1. purge first: removing Strikes/curses improves every future draw
    if "purge" in ch and gold >= purge_cost + 90:
        junk = [c for c in deck_ids
                if c in REMOVE_PRIORITY or (c or "").startswith("Curse")]
        if junk or len(deck) >= 15:
            cmd = buy("purge", "thin deck (%s)" % (junk[0] if junk else "size"))
            if cmd:
                return cmd

    # 2. relic deals that don't bankrupt us
    for r in relics:
        price = r.get("price") or 9999
        if price <= gold - 80:
            cmd = buy(r.get("name"), "relic %dg" % price)
            if cmd:
                return cmd

    # 3. cards: act-aware bar (early growth, late only power)
    affordable = [c for c in cards if (c.get("price") or 9999) <= gold - 60]
    scored = [(CARD_TIER.get(c.get("id") or "", 1)
               + synergy_bonus(c.get("id") or "", deck_ids)
               + relic_syn(c.get("id") or "", relics_held)
               + boss_syn(c.get("id") or "", g.get("act_boss") or ""), c)
              for c in affordable]
    bar = 2.0 if act == 1 else 2.5
    good = [t for t in scored if t[0] >= bar]
    if good:
        best = max(good, key=lambda t: t[0])
        cmd = buy(best[1].get("name"), "tier+syn %.1f" % best[0])
        if cmd:
            return cmd

    # 4. potions with a free slot (never with Sozu)
    slots_free = any((p.get("id") or "") == "Potion Slot"
                     for p in (g.get("potions") or []))
    if slots_free and "Sozu" not in relics_held:
        for p in potions:
            if (p.get("price") or 9999) <= gold - 40:
                pid = (p.get("id") or "").replace(" ", "")
                if pid in POTION_CATALOG:
                    cmd = buy(p.get("name"), "potion %dg" % p.get("price"))
                    if cmd:
                        return cmd

    # done shopping: leave (this game version's leave button is "proceed")
    ctx.shop_seen += 1
    for a in avail_u:
        if a.upper() in ("RETURN", "SKIP", "CANCEL", "LEAVE"):
            return a.upper()
    for a in avail_u:
        if a.upper() in ("PROCEED", "CONFIRM"):
            return "PROCEED"
    return "CHOOSE 1"


def rest_action(state, avail_u):
    """Weighted rest vs smith: heal value (no overheal) vs upgrade value
    (key un-upgraded cards), adjusted for boss proximity and regen relics."""
    g = gs(state)
    ch = [str(c) for c in choices(state)]
    hp = g.get("current_hp") or 1
    max_hp = g.get("max_hp") or 1
    floor = g.get("floor") or 0
    act = g.get("act") or 1
    if not ch:
        return "CHOOSE 0"
    def find(*keys):
        for i, n in enumerate(ch):
            if any(k in n for k in keys):
                return i
        return None

    frac = hp / float(max_hp)
    deficit_frac = (max_hp - hp) / float(max_hp)
    heal_frac = 0.30  # rest heals 30% max hp
    rest_v = min(deficit_frac, heal_frac) * 1.2
    if deficit_frac < 0.15:
        rest_v *= 0.4  # most of the heal would overheal
    if deficit_frac > heal_frac + 0.15:
        rest_v += 0.15  # deep red: extra push
    boss_floor = {1: 16, 2: 33, 3: 51}.get(act, 16)
    if floor >= boss_floor - 3 and frac < 0.85:
        rest_v += 0.20  # bring HP into the boss fight
    relic_ids = [r.get("id") for r in (g.get("relics") or [])]
    if set(relic_ids) & REGEN_RELICS:
        rest_v -= 0.08  # sustain relics heal through combats

    deck = g.get("deck") or []
    key_left = [c.get("id") for c in deck
                if (c.get("id") in UPGRADE_PRIORITY[:18])
                and (c.get("upgrades") or 0) == 0]
    smith_v = 0.25
    if key_left:
        smith_v += 0.15 + min(0.10, 0.03 * len(key_left))
    if act == 1:
        smith_v += 0.05

    if frac <= 0.45:
        decision = "rest"
    else:
        decision = "rest" if rest_v >= smith_v else "smith"
    log("campfire: rest %.2f vs smith %.2f (key upgrades left: %s) -> %s" % (
        rest_v, smith_v, key_left[:4] or "-", decision))
    if decision == "rest":
        i = find("休息", "rest")
        if i is not None:
            return "CHOOSE %d" % i
    i = find("锻造", "升级", "smith", "upgrade")
    if i is not None:
        return "CHOOSE %d" % i
    if decision == "rest":
        pass
    i = find("回忆", "dig", "观察")
    if i is not None:
        return "CHOOSE %d" % i
    return "CHOOSE 0"

def map_action(state, avail_u):
    """Look-ahead path scoring: beam-search 6 rows deep over the full map,
    score whole paths (decayed by depth), take the first step of the best."""
    g = gs(state)
    nodes = scr(state).get("next_nodes") or []
    ch = choices(state)
    if not nodes or not ch:
        return "CHOOSE 0"
    full = {}
    for n in (g.get("map") or []):
        full[(n.get("x"), n.get("y"))] = n
    hp = g.get("current_hp") or 1
    max_hp = g.get("max_hp") or 1
    frac = hp / float(max_hp) if max_hp else 1.0
    gold = g.get("gold") or 0
    floor = g.get("floor") or 0
    deck_size = len(g.get("deck") or [])

    deck_power = 0
    for c in (g.get("deck") or []):
        t = CARD_TIER.get(c.get("id") or "", 1)
        if t >= 2.5:
            deck_power += 2
        elif t >= 2:
            deck_power += 1
        if (c.get("upgrades") or 0) > 0:
            deck_power += 1
    if (g.get("act") or 1) == 1:
        elite_ready = frac >= 0.85 and deck_power >= 8  # act-1 elites eat weak decks
    else:
        elite_ready = frac >= 0.80 and deck_power >= 6

    def nscore(sym):
        if sym == "R":
            if frac < 0.45:
                return 3.5
            if frac < 0.55:
                return 3.0
            if frac < 0.7:
                return 3.0 if floor >= 12 else 2.6  # pre-boss: heal up hard
            return 2.6 if floor >= 13 else 2.0
        if sym == "M":
            w = 1.4 if deck_size < 18 else 1.0
            if frac < 0.25:
                w -= 3.0  # dying: fights can kill us outright
            elif frac < 0.4:
                w -= 1.0
            elif frac < 0.7:
                w -= 0.3  # chipped: prefer safer nodes at equal value
            return w
        if sym == "?":
            w = 1.1 if floor < 12 else 0.8
            if frac < 0.4:
                w += 1.0  # events can heal
            return w
        if sym == "$":
            if frac < 0.35:
                return -2.0  # gold can't save a dead run
            return 1.6 if gold >= 150 else -0.5
        if sym == "E":
            if elite_ready:
                return 2.0  # relic worth it only with a deck that can fight
            if frac >= 0.60:
                return -2.0
            return -8.0
        if sym == "T":
            return 2.0
        return 0.5

    def best_from(node, depth):
        if depth >= 7 or not node:
            return 0.0
        best = 0.0
        for k in (node.get("children") or []):
            child = full.get((k.get("x"), k.get("y")))
            if child is None:
                continue
            v = nscore(child.get("symbol")) * (0.85 ** depth) + best_from(child, depth + 1)
            if v > best:
                best = v
        return best

    scores = []
    for st_node in nodes:
        node = full.get((st_node.get("x"), st_node.get("y")))
        scores.append(nscore(st_node.get("symbol")) + best_from(node, 1))
    best_idx = max(range(len(nodes)), key=lambda i: scores[i])
    idx = min(best_idx, len(ch) - 1)
    log("map: scores %s -> %s (hp %.0f%%, gold %d)" % (
        [round(s, 1) for s in scores], nodes[best_idx].get("symbol"), frac * 100, gold))
    return "CHOOSE %d" % idx

def event_action(state, avail_u):
    ch = [str(c) for c in choices(state)]
    if not ch:
        return "CHOOSE 0"
    prefer = ("最大生命", "遗物", "金币", "获得", "升级", "回血", "移除", "卡牌")
    avoid = ("失去", "诅咒", "死亡", "受到伤害")
    best, best_score = 0, -99
    for i, n in enumerate(ch):
        score = 0
        if any(k in n for k in prefer):
            score += 2
        if any(k in n for k in avoid):
            score -= 3
        if "跳过" in n or "离开" in n:
            score -= 1
        if score > best_score:
            best, best_score = i, score
    return "CHOOSE %d" % best

class Ctx(object):
    menu_seen = 0
    shop_seen = 0
    shop_bought = False
    card_reward_done = False
    potion_attempted = False
    floor = None
    match_flips = 0      # "Match and Keep!" 事件翻牌计数

def combat_reward_action(state, ctx):
    g = gs(state)
    ch = [str(c) for c in choices(state)]
    def row(*keys):
        for i, n in enumerate(ch):
            if any(k in n.lower() for k in keys):
                return i
        return None
    # open the card row exactly once per room; after that never re-open it
    if not ctx.card_reward_done:
        i = row("card", "卡牌", "添加")
        if i is not None:
            return "CHOOSE %d" % i
        ctx.card_reward_done = True
    i = row("gold", "金币")
    if i is not None:
        return "CHOOSE %d" % i
    i = row("relic", "遗物")
    if i is not None:
        return "CHOOSE %d" % i
    # potion row only with a free slot (full inventory opens an untrackable
    # replace dialog -> softlock) and never with Sozu
    relics = relic_id_list(g)
    if "Sozu" not in relics and not ctx.potion_attempted:
        slots_free = any((p.get("id") or "") == "Potion Slot"
                         for p in (g.get("potions") or []))
        if slots_free:
            i = row("potion", "药水")
            if i is not None:
                ctx.potion_attempted = True
                return "CHOOSE %d" % i
    return "PROCEED"

def pick_command(state, ctx):
    avail = state.get("available_commands") or []
    if not avail:
        return "STATE"
    avail_u = [str(a).strip() for a in avail]
    avail_up = [a.upper() for a in avail_u]
    st = screen_type(state)
    room = (gs(state).get("room_type") or "").upper()

    if at_main_menu(state, avail_u):
        ctx.menu_seen += 1
        ctx.shop_seen = 0
        mode = "continue"
        try:
            if os.path.exists(MODE):
                m = open(MODE, "r", encoding="utf-8").read().strip().lower()
                if m:
                    mode = m
        except Exception:
            pass
        has_save = bool(glob.glob(r"D:\Steam\steamapps\common\SlayTheSpire\saves\*.autosave"))
        if mode == "continue" and has_save and ctx.menu_seen <= 5:
            return RESUME_CLICK
        log("menu: START IRONCLAD (menu_seen=%d has_save=%s)" % (ctx.menu_seen, has_save))
        return "START IRONCLAD"

    # 对对碰！(Match and Keep)：CommunicationMod 对该事件状态不完整，
    # 逐张翻牌把事件推进完（按键位循环，尽量多配对）
    if st == "EVENT" and "Match and Keep" in str(scr(state).get("event_id") or ""):
        ch = choices(state)
        if ch:
            idx = ctx.match_flips % len(ch)
            ctx.match_flips += 1
            return "CHOOSE %d" % idx
        return "KEY Cancel"
    if any(a.upper() == "CHOOSE" for a in avail_u):
        if st == "MAP":
            return map_action(state, avail_u)
        if st == "COMBAT_REWARD":
            return combat_reward_action(state, ctx)
        if "SHOP" in st or "SHOP" in room:
            return shop_action(state, avail_u, ctx)
        if st == "GRID":
            return grid_action(state, avail_u)
        if st == "CARD_REWARD":
            ctx.card_reward_done = True  # decided (take or skip): don't reopen
            return card_reward_action(state, avail_u)
        if "REST" in room or any("休息" in str(c) for c in choices(state)):
            return rest_action(state, avail_u)
        if st == "MAP":
            return map_action(state, avail_u)
        if st in ("EVENT", "GHOST") or "event" in st.lower():
            return event_action(state, avail_u)
        if st == "HAND_SELECT":
            return "CHOOSE 0"
        return "CHOOSE 0"

    if any(a.upper() == "PLAY" for a in avail_u) or "END" in avail_up:
        cmd = combat_action(state, avail_u)
        if cmd:
            return cmd

    if "END" in avail_up:
        return "END"
    for a in avail_up:
        if a in ("PROCEED", "CONFIRM"):
            return "PROCEED"
    for a in avail_up:
        if a in ("RETURN", "SKIP", "CANCEL", "LEAVE"):
            return "RETURN"
    for a in avail_up:
        if a == "WAIT":
            return "WAIT 60"
    return "STATE"

def main():
    log("driver v3 (strategy) started, pid=%d" % os.getpid())
    out("ready")
    n = 0
    last_sig = None
    repeat = 0
    hist = deque()
    ctx = Ctx()
    while True:
        raw = RAW_IN.readline()
        if not raw:
            break
        line = decode_in(raw).strip()
        if not line:
            continue
        n += 1
        try:
            state = json.loads(line)
        except ValueError:
            continue
        try:
            with open(LAST, "w", encoding="utf-8") as f:
                f.write(json.dumps(state, ensure_ascii=False, indent=1))
        except Exception:
            pass

        cmd = None
        try:
            if os.path.exists(MANUAL):
                with open(MANUAL, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    cmd = content.splitlines()[0].strip()
                    log("MANUAL command: %s" % cmd)
                os.remove(MANUAL)
        except Exception:
            pass

        if not cmd:
            try:
                cmd = pick_command(state, ctx)
            except Exception:
                import traceback
                log("DECISION CRASH:\n" + traceback.format_exc())
                cmd = "STATE"

        if not state.get("error"):
            if not at_main_menu(state, [str(a) for a in (state.get("available_commands") or [])]):
                ctx.menu_seen = 0
            if "SHOP" not in screen_type(state):
                ctx.shop_seen = 0

        # floor change resets per-room reward memory
        fl = gs(state).get("floor")
        if fl != ctx.floor:
            ctx.floor = fl
            ctx.card_reward_done = False
            ctx.potion_attempted = False
            ctx.match_flips = 0

        if screen_type(state) == "NONE" and (gs(state).get("combat_state") or {}).get("monsters"):
            mons_dbg = ",".join("%s(%d/%d)" % (m.get("id") or "?", m.get("current_hp") or 0, m.get("max_hp") or 0)
                                for m in (gs(state).get("combat_state") or {}).get("monsters", [])
                                if (m.get("current_hp") or 0) > 0)
            if mons_dbg and mons_dbg != getattr(main, "_last_mons", ""):
                main._last_mons = mons_dbg
                log("fight: vs %s" % mons_dbg)
        sig = (screen_type(state), gs(state).get("floor"), cmd,
               tuple(sorted(str(x) for x in (state.get("available_commands") or []))))
        hist.append((screen_type(state), cmd))
        if len(hist) > 8:
            hist.popleft()
        osc = False
        if len(hist) == 8:
            h = list(hist)
            if h[0:2] == h[2:4] == h[4:6] == h[6:8]:
                osc = True
        if osc:
            log("oscillation detected (%s<->%s), sleeping 3s" % (h[0][0], h[1][0]))
            time.sleep(3)
        if sig == last_sig:
            repeat += 1
            if repeat > 200:  # anti-spin guard
                log("stuck 200x, sleeping 5s")
                time.sleep(5)
                repeat = 0
        else:
            repeat = 0
            last_sig = sig
        time.sleep(0.1)  # pacing: keeps the game watchable, not strobing

        if state.get("error"):
            log("state %d error: %s" % (n, state.get("error")))
        log("state %d: screen=%s room=%s hp=%s floor=%s -> %s" % (
            n, screen_type(state) or "-", gs(state).get("room_type") or "-",
            gs(state).get("current_hp"), gs(state).get("floor"), cmd))
        out(cmd)

if __name__ == "__main__":
    main()
