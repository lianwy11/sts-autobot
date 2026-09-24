# -*- coding: utf-8 -*-
# Slay the Spire driver v3 for CommunicationMod.
# One decision per state line; the mod re-sends state after every command.
import sys, json, os, io, time, glob, random
from collections import deque

BASE = os.path.dirname(os.path.abspath(__file__))
MANUAL = os.path.join(BASE, "manual_cmd.txt")
MODE = os.path.join(BASE, "mode.txt")
CHARACTER = os.path.join(BASE, "character.txt")
LOG = os.path.join(BASE, "driver_log.txt")
LAST = os.path.join(BASE, "last_state.json")

# 玩哪个职业：character.txt 写 IRONCLAD / THE_SILENT / DEFECT / WATCHER 之一，
# 或 RANDOM（每局随机）/ ROTATE（每局轮换）。锁定的职业自动跳过。
# CommunicationMod 的 START 命令按枚举名匹配（大小写不敏感，SILENT 会被映射成 THE_SILENT）。
PLAYABLE = {"IRONCLAD", "THE_SILENT", "SILENT", "DEFECT", "WATCHER"}
ALL_CLASSES = ["IRONCLAD", "THE_SILENT", "DEFECT", "WATCHER"]
ROTATE_STATE = os.path.join(BASE, "rotate_count.txt")

def read_rotate_count():
    """ROTATE 计数持久化：驱动重启（改代码/崩溃恢复）不该让轮换回到铁甲。"""
    try:
        return int(open(ROTATE_STATE, "r", encoding="utf-8").read().strip())
    except Exception:
        return 0

def bump_rotate_count():
    n = read_rotate_count() + 1
    try:
        with open(ROTATE_STATE, "w", encoding="utf-8") as f:
            f.write(str(n))
    except Exception:
        pass
    return n

def read_character_pref():
    try:
        if os.path.exists(CHARACTER):
            c = open(CHARACTER, "r", encoding="utf-8").read().strip().upper()
            if c:
                return c
    except Exception:
        pass
    return "IRONCLAD"

def desired_character(ctx):
    pref = read_character_pref()
    locked = getattr(ctx, "locked_classes", set()) or set()
    pool = [c for c in ALL_CLASSES if c not in locked] or ["IRONCLAD"]
    if pref == "RANDOM":
        return random.choice(pool)
    if pref == "ROTATE":
        return pool[read_rotate_count() % len(pool)]
    want = "THE_SILENT" if pref == "SILENT" else pref
    if want in PLAYABLE and want not in locked:
        return want
    if want in locked:
        log("class %s locked, falling back" % want)
    return random.choice(pool)

RESUME_CLICK = "CLICK LEFT 205 631"
# 主菜单"继续"按钮：实测桌面 (460,627)，窗口客户区原点 (323,206)、缩放 0.6667
# （1280x720 窗口跑 1920x1080 逻辑分辨率）→ 逻辑坐标 (205,631)。
# 旧值 (240,660) 会落在"放弃当前游戏"上，触发放弃确认框毁掉存档。
# 对话框的"否"按钮：桌面 (1026,665) → 逻辑 (1054,688)
DIALOG_NO_CLICK = "CLICK LEFT 1054 688"

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
    # Ironclad gaps (seen skipped/misplayed in run logs)
    "Body Slam": (0, 1, 0, ""), "Cleave": (8, 1, 0, ""),
    "Clash": (14, 1, 0, ""), "Sword Boomerang": (3, 3, 0, ""),
    "Wild Strike": (12, 1, 0, ""), "Reckless Charge": (7, 1, 0, ""),
    "Pummel": (2, 4, 0, ""), "Bludgeon": (32, 1, 0, ""),
    "Perfected Strike": (6, 1, 0, ""), "Immolate": (21, 1, 0, ""),
    "Thunderclap": (4, 1, 0, "vuln"), "Demon Form": (0, 1, 0, "buff"),
    "Limit Break": (0, 1, 0, "buff"), "Corruption": (0, 1, 0, "buff"),
    "Barricade": (0, 1, 0, "buff"), "Ghostly Armor": (0, 1, 10, ""),
    "Entrench": (0, 1, 0, ""), "Power Through": (0, 1, 15, ""),
    "Second Wind": (0, 1, 5, ""), "Disarm": (0, 1, 0, "weak"),
    "Shockwave": (0, 1, 0, "weak"), "Intimidate": (0, 1, 0, "weak"),
    "Seeing Red": (0, 1, 0, "energy"), "Burning Pact": (0, 1, 0, "energy"),
    "Bloodletting": (0, 1, 0, "energy"), "Battle Trance": (0, 1, 0, ""),
    "Warcry": (0, 1, 0, ""), "Dual Wield": (0, 1, 0, ""),
    "Infernal Blade": (0, 1, 0, ""), "Havoc": (0, 1, 0, ""),
    "Evolve": (0, 1, 0, "buff"), "Feel No Pain": (0, 1, 0, "buff"),
    "Dark Embrace": (0, 1, 0, "buff"), "Fire Breathing": (0, 1, 0, "buff"),
    "Rupture": (0, 1, 0, "buff"), "Brutality": (0, 1, 0, "buff"),
    "Juggernaut": (0, 1, 0, "buff"), "Rage": (0, 1, 0, "buff"),
    "Combust": (0, 1, 0, "buff"), "Exhume": (0, 1, 0, ""),
    # Silent gaps
    "Deflect": (0, 1, 4, ""), "Flying Knee": (11, 1, 0, ""),
    "Riddle with Holes": (3, 4, 0, ""), "Storm of Steel": (0, 1, 0, ""),
    "Infinite Blades": (0, 1, 0, "buff"),
    # Defect core (rough values; fallback covers the rest)
    "Strike_B": (6, 1, 0, ""), "Defend_B": (0, 1, 5, ""),
    "Ball Lightning": (8, 1, 0, ""), "Cold Snap": (6, 1, 0, ""),
    "Coolheaded": (0, 1, 4, ""), "Compile Driver": (7, 1, 0, ""),
    "Go for the Eyes": (3, 1, 0, "weak"), "Beam Cell": (3, 1, 0, "vuln"),
    "Rip and Tear": (5, 2, 0, ""), "Sweeping Beam": (6, 1, 0, ""),
    "Charge Battery": (0, 1, 7, ""), "Glacier": (0, 1, 7, ""),
    "Hologram": (0, 1, 3, ""), "Rebound": (9, 1, 0, ""),
    # Defect rest
    "Leap": (0, 1, 9, ""), "Steam Barrier": (0, 1, 7, ""),
    "Auto-Shields": (0, 1, 11, ""), "Equilibrium": (0, 1, 13, ""),
    "Force Field": (0, 1, 4, ""), "Genetic Algorithm": (0, 1, 3, ""),
    "Blitz": (7, 1, 0, ""), "Bullseye": (8, 1, 0, ""),
    "Claw": (3, 1, 0, ""), "Doom and Gloom": (10, 1, 0, ""),
    "Melter": (10, 1, 0, ""), "Scrape": (7, 1, 0, ""),
    "Streamline": (15, 1, 0, ""), "Sunder": (24, 1, 0, ""),
    "FTL": (4, 1, 0, ""), "All For One": (10, 1, 0, ""),
    "Hyperbeam": (26, 1, 0, ""), "Thunder Strike": (7, 3, 0, ""),
    "Core Surge": (11, 1, 0, ""),
    "Blizzard": (0, 1, 0, "buff"), "Tempest": (0, 1, 0, "buff"),
    "Defragment": (0, 1, 0, "buff"), "Biased Cognition": (0, 1, 0, "buff"),
    "Capacitor": (0, 1, 0, "buff"), "Loop": (0, 1, 0, "buff"),
    "Consume": (0, 1, 0, "buff"), "Amplify": (0, 1, 0, "buff"),
    "Storm": (0, 1, 0, "buff"), "Static Discharge": (0, 1, 0, "buff"),
    "Self Repair": (0, 1, 0, "buff"), "Creative AI": (0, 1, 0, "buff"),
    "Buffer": (0, 1, 0, "buff"), "Fission": (0, 1, 0, "energy"),
    "Double Energy": (0, 1, 0, "energy"), "Recursion": (0, 1, 0, ""),
    "Darkness": (0, 1, 0, ""), "Fusion": (0, 1, 0, ""),
    "Chill": (0, 1, 0, ""), "Skim": (0, 1, 0, ""),
    "Overclock": (0, 1, 0, ""), "White Noise": (0, 1, 0, ""),
    # Watcher core (stance doubling not modeled; rough values)
    "Strike_P": (6, 1, 0, ""), "Defend_P": (0, 1, 5, ""),
    "Eruption": (9, 1, 0, ""), "Vigilance": (0, 1, 8, ""),
    "Crush Joints": (8, 1, 0, ""), "Sash Whip": (8, 1, 0, "weak"),
    "Flurry of Blows": (4, 1, 0, ""), "Follow-Up": (7, 1, 0, ""),
    "Flying Sleeves": (4, 2, 0, ""), "Conclude": (12, 1, 0, ""),
    "Consecrate": (5, 1, 0, ""), "Crescendo": (0, 1, 0, ""),
    "Tranquility": (0, 1, 0, ""),
    # Watcher rest
    "Talk to the Hand": (5, 1, 0, ""), "Tantrum": (8, 1, 0, ""),
    "Reach Heaven": (10, 1, 0, ""), "Ragnarök": (12, 3, 0, ""),
    "Carve Reality": (13, 1, 0, ""), "Brilliance": (8, 1, 0, ""),
    "Lesson Learned": (10, 1, 0, ""), "Empty Fist": (9, 1, 0, ""),
    "Pressure Points": (8, 1, 0, ""), "Fear No Evil": (8, 1, 0, ""),
    "Halt": (0, 1, 3, ""), "Sanctity": (0, 1, 6, ""),
    "Inner Peace": (0, 1, 8, ""), "Spirit Shield": (0, 1, 6, ""),
    "Just Lucky": (0, 1, 3, ""), "Prostrate": (0, 1, 4, ""),
    "Empty Body": (0, 1, 7, ""), "Meditate": (0, 1, 0, ""),
    "Pray": (0, 1, 0, ""), "Devotion": (0, 1, 0, "buff"),
    "Foresight": (0, 1, 0, "buff"), "Nirvana": (0, 1, 0, "buff"),
    "Like Water": (0, 1, 0, "buff"), "Establishment": (0, 1, 0, "buff"),
    "Mental Fortress": (0, 1, 0, "buff"), "Rushdown": (0, 1, 0, "buff"),
    "Wave of the Hand": (0, 1, 0, ""), "Fasting": (0, 1, 0, "buff"),
    "Deus Ex Machina": (0, 1, 0, ""), "Collect": (0, 1, 0, ""),
    "Conjure Blade": (0, 1, 0, ""), "Judgment": (0, 1, 0, ""),
    "Blasphemy": (0, 1, 0, "buff"), "Wish": (0, 1, 0, "buff"),
    "Omega": (50, 1, 0, ""), "Vault": (0, 1, 0, ""),
    "Omniscience": (0, 1, 0, ""), "Scrawl": (0, 1, 0, ""),
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
    # Ironclad gaps
    "Body Slam": 3, "Cleave": 2.2, "Clash": 1.5, "Sword Boomerang": 2.2,
    "Wild Strike": 2, "Reckless Charge": 1.5, "Pummel": 2, "Bludgeon": 2.5,
    "Perfected Strike": 1, "Immolate": 3, "Thunderclap": 2,
    "Ghostly Armor": 2, "Entrench": 2.5, "Power Through": 2,
    "Disarm": 2.5, "Seeing Red": 2.5, "Burning Pact": 2,
    "Bloodletting": 2, "Infernal Blade": 2, "Evolve": 2, "Havoc": 1,
    "Dual Wield": 1.5, "Rage": 1, "Combust": 1, "Exhume": 2,
    # Silent gaps
    "Deflect": 1.5, "Flying Knee": 2.2, "Riddle with Holes": 2,
    "Storm of Steel": 2.5, "Infinite Blades": 2.5,
    # Defect
    "Ball Lightning": 2.5, "Cold Snap": 2.2, "Coolheaded": 2.2,
    "Compile Driver": 2, "Go for the Eyes": 2, "Beam Cell": 1.5,
    "Rip and Tear": 2, "Sweeping Beam": 2, "Charge Battery": 2.5,
    "Glacier": 2.5, "Hologram": 2, "Rebound": 2,
    "Hyperbeam": 3, "Multi-Cast": 3, "Creative AI": 3, "All For One": 2.5,
    "Equilibrium": 2, "Loop": 2.5, "Capacitor": 2, "Auto-Shields": 2,
    "Defragment": 3.5, "Biased Cognition": 3, "Buffer": 3,
    "Blizzard": 2.5, "Tempest": 2.5, "Force Field": 2.5,
    "Genetic Algorithm": 2.5, "Self Repair": 2.5, "Chill": 2.5,
    "Static Discharge": 2.5, "Rainbow": 2.5, "Reboot": 2.5,
    "Core Surge": 2.5, "Fission": 2, "Double Energy": 2.5,
    "Amplify": 2.5, "Consume": 2, "Doom and Gloom": 2, "Melter": 2,
    "Sunder": 2, "Streamline": 2, "FTL": 2, "Claw": 2,
    "Bullseye": 2, "Blitz": 1.5, "Scrape": 1.5, "Steam Barrier": 1.5,
    "Leap": 1.5, "Storm": 2, "Darkness": 2, "White Noise": 2,
    "Hello World": 2, "Skim": 2, "Overclock": 1.5, "Recursion": 1.5,
    "Fusion": 1.5, "Heatsinks": 1.5, "Reprogram": 1.5,
    # Watcher
    "Crush Joints": 2, "Sash Whip": 2, "Flurry of Blows": 2.2,
    "Follow-Up": 2.2, "Flying Sleeves": 2.2, "Conclude": 1.5,
    "Consecrate": 2, "Crescendo": 1.5, "Tranquility": 1.5,
    "Rushdown": 3, "Scrawl": 3.5, "Mental Fortress": 2.5,
    "Wave of the Hand": 2.5, "Lesson Learned": 3, "Blasphemy": 2.5,
    "Wish": 3, "Omega": 3, "Conjure Blade": 2, "Talk to the Hand": 2.5,
    "Tantrum": 2.5, "Meditation": 2, "Empty Body": 1.5, "Empty Fist": 2,
    "Just Lucky": 1.5,
    "Vault": 3.5, "Omniscience": 3, "Ragnarök": 2.5, "Carve Reality": 2.5,
    "Reach Heaven": 2.5, "Brilliance": 2.5, "Inner Peace": 2.5,
    "Fear No Evil": 2.5, "Spirit Shield": 2.5, "Sanctity": 2,
    "Pressure Points": 2, "Fasting": 2.5, "Foresight": 2,
    "Devotion": 2, "Halt": 2, "Protect": 2, "Pray": 1.5,
    "Prostrate": 1.5, "Deus Ex Machina": 2.5, "Establishment": 2.5,
    "Like Water": 2, "Nirvana": 2, "Judgment": 2, "Collect": 2,
    "Master Reality": 2.5, "Simmer": 1.5, "Foreign Influence": 2,
    "Falcon Punch": 2, "Battle Hymn": 2,
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
# per-class upgrade order (earlier = upgrade first)
UPGRADE_PRIORITY_BY_CLASS = {
    "IRONCLAD": [
        "Demon Form", "Limit Break", "Bash", "Inflame", "Spot Weakness",
        "Feed", "Immolate", "Body Slam", "Uppercut", "Carnage",
        "Heavy Blade", "Whirlwind", "Impervious", "Juggernaut",
        "Second Wind", "Shockwave", "Dark Embrace", "Shrug It Off",
        "Metallicize", "Offering", "Reaper", "Corruption", "Barricade",
        "Thunderclap", "Cleave", "Twin Strike", "Pommel Strike",
        "Strike_R", "Defend_R",
    ],
    "THE_SILENT": [
        "Adrenaline", "Corpse Explosion", "Die Die Die", "Wraith Form",
        "Burst", "Terror", "Noxious Fumes", "Bouncing Flask", "Footwork",
        "Predator", "Blade Dance", "Backstab", "Poisoned Stab",
        "Eviscerate", "Caltrops", "Leg Sweep", "Backflip", "Deadly Poison",
        "Sucker Punch", "Dagger Spray", "Cloak and Dagger", "Acrobatics",
        "Slice", "Neutralize", "Strike_G", "Defend_G", "Survivor",
    ],
    "DEFECT": [
        "Multi-Cast", "Creative AI", "Hyperbeam", "All For One",
        "Defragment", "Biased Cognition", "Loop", "Capacitor", "Glacier",
        "Charge Battery", "Coolheaded", "Cold Snap", "Ball Lightning",
        "Sweeping Beam", "Compile Driver", "Rip and Tear", "Equilibrium",
        "Hologram", "Auto-Shields", "Self Repair", "Force Field",
        "Chill", "Static Discharge", "Tempest", "Blizzard",
        "Go for the Eyes", "Beam Cell", "Strike_B", "Defend_B", "Leap",
    ],
    "WATCHER": [
        "Wish", "Vault", "Omniscience", "Rushdown", "Scrawl", "Tantrum",
        "Talk to the Hand", "Mental Fortress", "Lesson Learned",
        "Blasphemy", "Wave of the Hand", "Ragnarök", "Carve Reality",
        "Reach Heaven", "Inner Peace", "Fear No Evil", "Spirit Shield",
        "Sanctity", "Empty Fist", "Conclude", "Flurry of Blows",
        "Crush Joints", "Sash Whip", "Follow-Up", "Flying Sleeves",
        "Fasting", "Meditate", "Deus Ex Machina", "Establishment",
        "Halt", "Protect", "Eruption", "Vigilance",
        "Strike_P", "Defend_P",
    ],
}

def upgrade_priority_for(state):
    cls = ((gs(state).get("class") or "IRONCLAD") + "").upper()
    if cls == "SILENT":
        cls = "THE_SILENT"
    return UPGRADE_PRIORITY_BY_CLASS.get(cls, UPGRADE_PRIORITY)

REMOVE_PRIORITY = ["Regret", "Injury", "Clumsy", "Decay", "Doubt", "Shame",
                    "Normality", "Pain", "Void",
                    "Strike_G", "Strike_R", "Strike_B", "Strike_P",
                    "Survivor", "Defend_G", "Defend_R", "Defend_B", "Defend_P"]
# Eruption/Vigilance never removed: they are the Watcher's stance engine

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
# Defect: frost orbs block, focus multiplies every orb
FROST_CORE = {"Glacier", "Cold Snap", "Coolheaded", "Tempest", "Blizzard",
              "Auto-Shields", "Fusion", "Chill"}
FOCUS_CORE = {"Defragment", "Biased Cognition", "Capacitor", "Loop",
              "Amplify", "Consume"}
# Watcher: stance entries need payoffs and vice versa
STANCE_ENTER = {"Eruption", "Tantrum", "Crescendo", "Tranquility",
                "Fear No Evil", "Inner Peace", "Blasphemy", "Wrathful Stand",
                "Simmer", "Meditate"}
STANCE_PAYOFF = {"Mental Fortress", "Rushdown", "Talk to the Hand",
                 "Wave of the Hand", "Fasting", "Like Water", "Nirvana",
                 "Brilliance", "Establishment", "Scrawl"}

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
    # Defect frost/focus engine
    if card_id in FROST_CORE and n(FOCUS_CORE) >= 1:
        b += 1.0
    if card_id in FOCUS_CORE and n(FROST_CORE) >= 2:
        b += 1.0
    # Watcher stance dance
    if card_id in STANCE_PAYOFF and n(STANCE_ENTER) >= 3:
        b += 1.0
    if card_id in STANCE_ENTER and n(STANCE_PAYOFF) >= 2:
        b += 0.75
    return b

BAD_RELICS = set()  # buy nothing known-harmful; relic pool is mostly good

REGEN_RELICS = {"Burning Blood", "Magic Flower", "Black Blood"}  # sustain lowers rest value
POTION_BAN_RELICS = {"Sozu"}  # cannot drink potions at all
STAT_ATTACK_RELICS = {"Shuriken", "Kunai"}  # every 3 attacks -> str/dex

def relic_id_list(g):
    return [r.get("id") for r in (g.get("relics") or [])]

BOSS_AOE = {"Whirlwind", "Thunderclap", "Cleave", "Immolate", "Fire Breathing",
            "Dagger Spray", "All-Out Attack", "Corpse Explosion", "Die Die Die"}
# act-2 packs (3 Byrds, Cultists, Snake Plant + followers...) demand AoE
AOE_ATTACKS = BOSS_AOE | {"Rip and Tear", "Sweeping Beam", "Consecrate",
                          "Reaper", "Riddle with Holes", "Tempest", "FTL"}
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

# Act-boss relic pick after floor 16/33/51: engine relics first, rest-hostile
# ones (Sozu/Coffee Dripper) last. Keys are English relic ids.
BOSS_RELIC_TIER = {
    "Snecko Eye": 5.0, "Runic Pyramid": 4.5, "Pandora's Box": 4.5,
    "Astrolabe": 4.0, "Sacred Bark": 3.5, "Philosopher's Stone": 3.5,
    "Wrist Blade": 3.5, "Black Star": 3.0, "Velvet Choker": 3.0,
    "Tiny House": 3.0, "Runic Dome": 2.5, "Ectoplasm": 2.0,
    "Ring of the Serpent": 3.0, "Ring of the Snake": 3.0,
    "Busted Crown": 1.0, "Mark of Pain": 1.5, "SlaversCollar": 0.5,
    "Coffee Dripper": 0.8, "Sozu": 0.8,
}

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
    cid = card.get("id") or ""
    if cid == "Body Slam":
        dmg = (player.get("block") or 0)  # damage equals current block
    if dmg <= 0:
        return 0
    strn = power_amount(player.get("powers"), "Strength")
    dmg += strn
    if has_power(player.get("powers"), "Weak"):
        dmg = int(dmg * 0.75)
    if SHADOW_STANCE[0] == "WRATH":       # Watcher: double damage dealt
        dmg = int(dmg * 2)
    elif SHADOW_STANCE[0] == "DIVINITY":
        dmg = int(dmg * 3)
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

def living_monsters(state):
    """True if the reported combat still has living enemies (the reliable
    'fight is live' signal; room_phase/action_phase can lag behind)."""
    cs = gs(state).get("combat_state") or {}
    return any((m.get("current_hp") or 0) > 0 and not m.get("is_gone")
               and not m.get("half_dead")
               for m in (cs.get("monsters") or []))

# ---- Watcher stance shadow-tracking (the mod does not report stances) ----
# Cards we KNOW change stance; the driver tracks the belief across its own
# plays so Wrath's damage doubling can be respected.
STANCE_WRATH_CARDS = {"Eruption", "Tantrum", "Crescendo", "Wrathful Stand"}
STANCE_CALM_CARDS = {"Tranquility", "Inner Peace", "Fear No Evil", "Calm"}
SHADOW_STANCE = [None]  # None / "WRATH" / "CALM" / "DIVINITY"

def note_stance_card(cid):
    if cid in STANCE_WRATH_CARDS:
        SHADOW_STANCE[0] = "WRATH"
    elif cid in STANCE_CALM_CARDS:
        SHADOW_STANCE[0] = "CALM"
    elif cid == "Blasphemy":
        SHADOW_STANCE[0] = "DIVINITY"

def frost_orb_block(player):
    """Passive block frost orbs will add at end of turn (Defect)."""
    total = 0
    for o in (player.get("orbs") or []):
        nm = (o.get("id") or "") + (o.get("name") or "")
        if "Frost" in nm or "霜" in nm:
            total += o.get("passive_amount") or 0
    return total

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
    bar = 6 if easy_fight else (2 if "BOSS" in room_u else (3 if is_elite_or_boss(g) else 5))
    if hp_frac <= 0.3:
        bar = 0  # about to die: any potion that helps, now
    if (g.get("floor") or 0) >= 13 and "BOSS" not in room_u and not is_elite_or_boss(g):
        bar += 1  # pre-boss floors: mild hoarding for the act boss
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
    if SHADOW_STANCE[0] == "WRATH":
        incoming = int(incoming * 2)  # Watcher takes double in Wrath
    hp = player.get("current_hp") or g.get("current_hp") or 1
    max_hp = player.get("max_hp") or g.get("max_hp") or 1
    hp_frac = hp / float(max_hp) if max_hp else 1.0
    cur_block = player.get("block") or 0
    residual = max(0, incoming - cur_block - frost_orb_block(player))
    big_fight = is_elite_or_boss(g)
    mon_hp_max = max((m.get("current_hp") or 0) + (m.get("block") or 0) for _, m in mons)

    playable = [(i, c) for i, c in enumerate(hand, 1) if c.get("is_playable")]

    def play_card(i, c):
        """Targeted skills (Leg Sweep, Terror, Fear No Evil...) need an enemy
        index or the game rejects the command; untargeted cards must NOT get
        one. Attacks pick their target at each call site."""
        if c.get("has_target"):
            tgt = max(mons, key=lambda rm: monster_intent_damage(rm[1]))[0]
            return "PLAY %d %d" % (i, tgt)
        return "PLAY %d" % i
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

    # Blasphemy kills us at the start of next turn unless it ends the fight:
    # only the lethal branch above may ever play it
    attacks = [p for p in attacks if (p[1].get("id") or "") != "Blasphemy"]

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
            return play_card(blk_all[0][0], blk_all[0][1])

    # 2d. Watcher: leaving Wrath before a doubled hit beats blocking half of it
    if SHADOW_STANCE[0] == "WRATH" and residual >= max(6, int(hp * 0.2)):
        for i, c in skills:
            if (c.get("id") or "") in STANCE_CALM_CARDS:
                log("wrath exit: %d doubled incoming -> calm" % incoming)
                return play_card(i, c)

    # 3. block policy: bosses near-full block, elites/boss 4, else 6
    #    (a chipped deck in act 1 blocks one point earlier to stop attrition)
    mon_ids = "|".join((m.get("id") or "") + (m.get("name") or "") for _, m in mons)
    if "GremlinNob" in mon_ids or "地精大汉" in mon_ids:
        threshold = 4  # enrage adds +2 str/skill, but unblocked 20-dmg turns kill
    elif "Lagavulin" in mon_ids and incoming > 0:
        threshold = 3  # awake Lagavulin: 18-20 per turn, must block
    elif "BOSS" in (g.get("room_type") or "").upper():
        threshold = 3
    elif big_fight or hp_frac < 0.5:
        threshold = 4
    elif hp_frac < 0.65:
        threshold = 5
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
            return play_card(i, c)

    # 5. develop powers when safe
    if residual < threshold and powers:
        good = [(i, c) for i, c in powers if card_info(c)[3] in ("buff", "energy")]
        if good:
            return play_card(good[0][0], good[0][1])

    # 5b. Defect orb setup: Zap/Dualcast deal no damage on cast (channel/evoke)
    # so the value tables skip them; play them while safe or the energy is
    # simply wasted every turn of act 1
    if residual < threshold and (g.get("class") or "").upper() == "DEFECT":
        has_orb = bool(player.get("orbs"))
        for i, c in skills:
            cid = c.get("id") or ""
            if cid == "Zap" or (cid == "Dualcast" and has_orb):
                return play_card(i, c)

    # 6. poison on long fights; commit harder when the deck is a poison build
    deck_ids = [c.get("id") for c in (g.get("deck") or [])]
    poison_build = sum(1 for c in deck_ids if c in POISON_CORE) >= 3
    if mon_hp_max > (25 if poison_build else 40):
        for i, c in skills + attacks:
            if card_info(c)[3] == "poison":
                threat = max(mons, key=lambda rm: (rm[1].get("current_hp") or 0))
                return "PLAY %d %d" % (i, threat[0])

    # 7. biggest attack, avoid dumping into heavy block; AOE first vs wide boards
    if attacks:
        if (g.get("act_boss") or "") == "Slime Boss" and len(mons) >= 2:
            aoe = [p for p in attacks if (p[1].get("id") or "") in BOSS_AOE]
            if aoe:
                i, c = aoe[0]
                return "PLAY %d 0" % i
        if len(mons) >= 3:
            # act-2 packs: hitting every body once beats single-target damage
            aoe = [p for p in attacks if (p[1].get("id") or "") in AOE_ATTACKS]
            if aoe:
                best_aoe = max(aoe, key=lambda p: estimated_attack(p[1], player))
                return "PLAY %d 0" % best_aoe[0]
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
            return play_card(blk_cards[0][0], blk_cards[0][1])

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
    # GRID = smith upgrade (RestRoom), purge (shop/events), or a multi-select
    # like Astrolabe ("transform 3 cards") after the act-boss relic pick
    room = (gs(state).get("room_type") or "").upper()
    ss = scr(state)
    cards = ss.get("cards") or []
    ch = [str(c) for c in choices(state)]
    selected = ss.get("selected_cards") or []
    need = ss.get("num_cards") or 1

    # all selections made (or a confirm-only screen): confirm, never re-click
    # (clicking a chosen card again DEselects it and the grid never completes)
    if (selected and len(selected) >= need) or (
            not ch and any(a.upper() == "CONFIRM" for a in avail_u)):
        for a in avail_u:
            if a.upper() == "CONFIRM":
                return a.upper()
    if not ch:
        return "CHOOSE 0"
    prio = upgrade_priority_for(state) if "REST" in room else REMOVE_PRIORITY
    def rank(c):
        cid = c.get("id") or ""
        if cid in prio:
            return prio.index(cid)
        return len(prio)
    # pick the best card not yet selected; with duplicate names click the
    # next unused occurrence so repeated strikes each get their own click
    sel_names = [str(c.get("name")) for c in selected]
    from collections import Counter
    sel_count = Counter(sel_names)
    for best in sorted(cards, key=rank):
        nm = str(best.get("name"))
        seen = 0
        for i, cand in enumerate(ch):
            if cand == nm:
                if seen == sel_count.get(nm, 0):
                    log("grid(%s): select '%s' (%d/%d)"
                        % ("smith" if "REST" in room else "purge/transform",
                           best.get("id"), len(selected) + 1, need))
                    return "CHOOSE %d" % i
                seen += 1
    for a in avail_u:
        if a.upper() == "CONFIRM":
            return a.upper()
    return "CHOOSE 0"

def boss_reward_action(state, avail_u):
    """Pick the best act-boss relic (engine relics > stats > rest-hostile)."""
    ss = scr(state)
    relics = ss.get("relics") or []
    ch = [str(c) for c in choices(state)]
    if not ch:
        return "CHOOSE 0"
    best_i, best_s, best_id = 0, -1.0, "?"
    for i in range(len(ch)):
        rid = (relics[i].get("id") or "") if i < len(relics) else ""
        s = BOSS_RELIC_TIER.get(rid, 2.0)  # unknown relic: assume average
        if s > best_s:
            best_i, best_s, best_id = i, s, rid
    log("boss relic: take %s (tier %.1f) of %s" % (
        best_id, best_s, [r.get("id") for r in relics] or ch))
    return "CHOOSE %d" % best_i

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
    if ch == ["shop"]:
        # shop room with the merchant unopened: enter once per floor
        if ctx.shop_entered_floor != ctx.floor:
            ctx.shop_entered_floor = ctx.floor
            log("shop room: entering merchant (floor %s)" % ctx.floor)
            return "CHOOSE 0"
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
    #    (once per floor: a failed purge flow must not loop)
    if ("purge" in ch and gold >= purge_cost + 90
            and ctx.purge_attempted_floor != ctx.floor):
        junk = [c for c in deck_ids
                if c in REMOVE_PRIORITY or (c or "").startswith("Curse")]
        if junk or len(deck) >= 15:
            cmd = buy("purge", "thin deck (%s)" % (junk[0] if junk else "size"))
            if cmd:
                ctx.purge_attempted_floor = ctx.floor
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
            return a.upper()
    return "KEY CANCEL"  # merchant with no leave button: ESC closes it


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
    if floor >= boss_floor - 4 and frac < 0.70:
        rest_v += 0.50  # entering the boss under 70% is how runs die
    relic_ids = [r.get("id") for r in (g.get("relics") or [])]
    if set(relic_ids) & REGEN_RELICS:
        rest_v -= 0.08  # sustain relics heal through combats

    deck = g.get("deck") or []
    key_left = [c.get("id") for c in deck
                if (c.get("id") in upgrade_priority_for(state)[:18])
                and (c.get("upgrades") or 0) == 0]
    smith_v = 0.15  # nothing key left: heal beats a sidegrade upgrade
    if key_left:
        smith_v += 0.15 + min(0.10, 0.03 * len(key_left))
    if act == 1:
        smith_v += 0.05
    if act >= 2:
        rest_v += 0.06  # act-2 chip damage snowballs; rest a bit more

    if frac <= (0.5 if act >= 2 else 0.45):
        decision = "rest"
    elif act == 1 and frac < 0.72:
        decision = "rest" if rest_v >= 0.18 else "smith"  # act-1 attrition
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
        elite_ready = frac >= 0.90 and deck_power >= 10  # act-1 elites eat weak decks
    else:
        elite_ready = frac >= 0.85 and deck_power >= 8  # act-2 elites are lethal
    act = g.get("act") or 1
    boss_floor = {1: 16, 2: 33, 3: 51}.get(act, 16)
    pre_boss = floor >= boss_floor - 4

    def nscore(sym):
        if sym == "R":
            if frac < 0.45:
                return 3.6
            if frac < 0.6:
                return 3.3
            if frac < 0.75:
                return 3.0 if act >= 2 else 2.9  # act 1: campfires keep runs alive
            if frac < 0.7:
                return 3.2 if pre_boss else 2.6  # pre-boss: heal up hard
            return (2.8 if pre_boss else 2.0) if act >= 2 else (2.6 if floor >= 13 else 2.0)
        if sym == "M":
            w = 1.4 if deck_size < 18 else 1.0
            if frac < 0.25:
                w -= 4.0  # dying: fights can kill us outright
            elif frac < 0.4:
                w -= 2.0
            elif frac < 0.6:
                w -= 1.0  # act-1 attrition: don't feed a hurt deck to packs
            elif frac < 0.7:
                w -= 0.3
            return w
        if sym == "?":
            w = 1.1 if floor < 12 else 0.8
            if frac < 0.4:
                w += 1.0  # events can heal
            return w
        if sym == "$":
            if frac < 0.35:
                return -2.0  # gold can't save a dead run
            if gold >= 250:
                return 2.6  # shops convert hoarded gold into deck power now
            if gold >= 150:
                return 1.8
            return -0.5
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
    shop_entered_floor = None  # 商店每层只进一次
    purge_attempted_floor = None  # 删卡每层只买一次（防死循环）
    start_fail = 0       # START 命令连续失败次数（职业未解锁等）
    locked_classes = set()  # START 失败判定为锁定的职业
    last_start_class = None
    runs_started = 0     # ROTATE 轮换计数
    start_sent = False   # 本次菜单会话只发一次 START
    stuck = 0            # 无指令可发的状态计数（过场/弹窗卡住）

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
        if mode == "continue" and has_save and ctx.menu_seen <= 40:
            # Continue click needs the menu faded in; menu keeps STILL showing
            # 'start' while the abandon dialog blocks it, so alternate with a
            # 'No' click (harmless no-op when no dialog is up) to escape it
            if ctx.menu_seen % 2 == 1:
                return DIALOG_NO_CLICK
            return RESUME_CLICK
        if ctx.start_sent:
            return "WAIT 60"  # one START per menu session; game is catching up
        ctx.start_fail = 0  # a fresh menu resets the failure streak
        # a class may have been unlocked mid-session (e.g. Silent just beat
        # act 1): retry locked classes once every 8 runs
        if ctx.runs_started and ctx.runs_started % 8 == 0 and ctx.locked_classes:
            log("retrying locked classes %s after 8 runs" % sorted(ctx.locked_classes))
            ctx.locked_classes.clear()
        char = desired_character(ctx)
        ctx.last_start_class = char
        ctx.runs_started += 1
        ctx.start_sent = True
        if "ROTATE" == read_character_pref().strip().upper():
            bump_rotate_count()  # persistent across driver restarts
        log("menu: START %s (menu_seen=%d has_save=%s run#%d rot#%d)"
            % (char, ctx.menu_seen, has_save, ctx.runs_started, read_rotate_count()))
        return "START %s" % char

    # 对对碰！(Match and Keep)：CommunicationMod 对该事件状态不完整，
    # 逐张翻牌把事件推进完（按键位循环，尽量多配对）
    if st == "EVENT" and "Match and Keep" in str(scr(state).get("event_id") or ""):
        ch = choices(state)
        if ch:
            idx = ctx.match_flips % len(ch)
            ctx.match_flips += 1
            return "CHOOSE %d" % idx
        return "KEY Cancel"
    if any(a.upper() == "CHOOSE" for a in avail_u) and not (
            st == "MAP" and living_monsters(state)):
        # MAP reported while monsters are still alive is a mod misdetection
        # (stale room_phase COMBAT after the fight too): clicking a node with
        # the fight live corrupts the game, so route those states to combat
        ctx.stuck = 0
        if st == "MAP":
            return map_action(state, avail_u)
        if st == "COMBAT_REWARD":
            return combat_reward_action(state, ctx)
        if st == "BOSS_REWARD":
            return boss_reward_action(state, avail_u)
        if st == "SHOP_ROOM":
            # standing in the shop room: 'shop' opens the merchant, but only
            # once per floor (after leaving, the choice reappears)
            ch = [str(c).lower() for c in choices(state)]
            if "shop" in ch and ctx.shop_entered_floor != ctx.floor:
                ctx.shop_entered_floor = ctx.floor
                log("shop room: entering merchant (floor %s)" % ctx.floor)
                return "CHOOSE %d" % ch.index("shop")
            for a in avail_u:
                if a.upper() in ("PROCEED", "CONFIRM"):
                    return a.upper()
            return "PROCEED"
        # GRID before the shop-room catch: purge opens a GRID while room_type
        # is still ShopRoom, and shop_action must not steal those states
        if st == "GRID":
            return grid_action(state, avail_u)
        if st == "CARD_REWARD":
            ctx.card_reward_done = True  # decided (take or skip): don't reopen
            return card_reward_action(state, avail_u)
        if "REST" in room or any("休息" in str(c) for c in choices(state)):
            return rest_action(state, avail_u)
        if st in ("EVENT", "GHOST") or "event" in st.lower():
            return event_action(state, avail_u)
        if st == "HAND_SELECT":
            return "CHOOSE 0"
        # room-based shop catch-all LAST: combat rewards can appear while
        # room_type is already ShopRoom; routed earlier, the reward cards
        # look like price-less shop stock and the reward flow loops
        if "SHOP" in st or "SHOP" in room:
            return shop_action(state, avail_u, ctx)
        return "CHOOSE 0"

    if any(a.upper() == "PLAY" for a in avail_u) or "END" in avail_up:
        cmd = combat_action(state, avail_u)
        if cmd:
            # record our own stance changes (mod never reports them)
            if cmd.startswith("PLAY "):
                try:
                    idx = int(cmd.split()[1]) - 1
                    hand = (gs(state).get("combat_state") or {}).get("hand") or []
                    if 0 <= idx < len(hand):
                        note_stance_card(hand[idx].get("id") or "")
                except Exception:
                    pass
            return cmd
        if not (gs(state).get("combat_state") or {}).get("monsters"):
            # 'end' listed but no fight: post-room overlay is blocking
            ctx.stuck += 1
            if ctx.stuck % 5 == 1:
                return "KEY CANCEL"
            return "WAIT 60"

    if "END" in avail_up:
        return "END"
    for a in avail_up:
        if a in ("PROCEED", "CONFIRM"):
            return a
    for a in avail_up:
        if a in ("RETURN", "SKIP", "CANCEL", "LEAVE"):
            return a
    # no actionable command but in-game and room finished: a story splash or
    # deck-view overlay is blocking us (seen after act-boss kills) -> dismiss
    if (state.get("in_game")
            and (gs(state).get("room_phase") or "").upper() == "COMPLETE"
            and not (gs(state).get("combat_state") or {}).get("monsters")):
        ctx.stuck += 1
        if ctx.stuck % 5 == 1:
            return "KEY CANCEL"  # paced: 1 dismiss per ~5 idle states
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
                ctx.start_sent = False  # left the menu (or resumed): re-arm
            if "SHOP" not in screen_type(state):
                ctx.shop_seen = 0

        # floor change resets per-room reward memory
        fl = gs(state).get("floor")
        if fl != ctx.floor:
            ctx.floor = fl
            ctx.card_reward_done = False
            ctx.potion_attempted = False
            ctx.match_flips = 0
            ctx.stuck = 0
            SHADOW_STANCE[0] = None  # new room: stance resets

        # START rejected 3x for the same class: lock it (not unlocked in this
        # save) and let desired_character pick a different one next menu
        if (state.get("error") and cmd
                and str(cmd).upper().startswith("START")
                and ctx.last_start_class):
            ctx.start_fail += 1
            if ctx.start_fail >= 3:
                if ctx.last_start_class not in ctx.locked_classes:
                    ctx.locked_classes.add(ctx.last_start_class)
                    log("START %s failed %dx -> class locked (unlocked?); locked=%s"
                        % (ctx.last_start_class, ctx.start_fail,
                           sorted(ctx.locked_classes)))
                ctx.start_fail = 0
                ctx.menu_seen = 99  # skip straight to a fresh START decision

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
