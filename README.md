# 杀戮尖塔 AI 代打机器人（Slay the Spire AutoBot）

一个用于《杀戮尖塔》(Slay the Spire) 的自动对战机器人：通过 `CommunicationMod` 协议接管游戏，用自研的 Python 决策引擎自动选卡、战斗、规划路线，并解决了 Steam 记录、后台运行、成就解锁等一系列配套问题。

> 本项目基于 **mod 模式** 运行，包含两个自研 Mod 补丁。仅供个人学习与自动化研究使用。

---

## 一、它能做什么

| 能力 | 说明 |
|---|---|
| **自动续档 / 开新局** | 启动后自动识别主菜单存档点击"继续游戏"，无存档则开新局 |
| **完整策略决策** | 选卡（含构筑倾向）、战斗（意图计算）、路线规划（6 层前瞻）、篝火（休息/锻造加权）、商店消费、药水估值、Boss 专项 |
| **后台无人值守** | 窗口失焦不暂停（自研 `NoFocusPause` Mod），可以挂着跑一整夜 |
| **Steam 集成** | 游玩时长正常记录（`steam_appid.txt`），成就正常解锁（自研 `AchievementEnabler` Mod）|
| **人工接管** | 运行中往 `manual_cmd.txt` 写一条指令即可插队执行（如 `PLAY 1 0`、`END`）|

### 战绩（参考）

- 已稳定通过第一幕 Boss（史莱姆王/守卫者/六火亡魂），进入第二幕
- 普通战斗近乎零失血（平均净失血 -0.4 HP/场），死亡集中在精英战与 Boss 战

---

## 二、系统架构

```
┌───────────────────────────── 游戏进程 (javaw.exe) ─────────────────────────────┐
│  desktop-1.0.jar（游戏本体）                                                    │
│    ├── ModTheSpire 3.30.3       Mod 加载器（支持 --mods 命令行参数）             │
│    ├── BaseMod 5.56.0            Mod 开发 API                                   │
│    ├── CommunicationMod 1.2.1   ★ 通信桥梁：把牌局状态以 JSON 发给外部进程         │
│    ├── NoFocusPause（自研）      ★ 禁用失焦自动暂停，支持后台运行                  │
│    └── AchievementEnabler（自研）★ 解除 mod 模式下的成就限制                      │
└───────────────────────────────────┬────────────────────────────────────────────┘
                                    │  stdin: 一行一个 JSON 状态
                                    │  stdout: 一行一条指令 (PLAY/END/CHOOSE/...)
                                    ▼
                        ┌───────────────────────────┐
                        │  driver.py（Python 决策引擎）│
                        │   · 战斗/选卡/路线/篝火/商店 │
                        │   · 药水估值/事件/Boss 专项  │
                        └───────────────────────────┘
```

**通信协议**（CommunicationMod 定义）：
- Mod 在状态稳定时向驱动进程 stdin 发送一行 JSON（手牌、怪物意图、地图、牌组、遗物、金币…）
- 驱动向 stdout 回一行指令，如 `PLAY 1 0`（打第 1 张牌给 0 号敌人）、`END`、`CHOOSE 2`、`POTION use 0`
- 每条指令执行后游戏送出新状态，形成"状态 → 决策 → 指令"闭环

---

## 三、目录结构

```
sts-autobot/
├── driver/
│   └── driver.py                 决策引擎（Python 3，无第三方依赖）
├── mods/
│   ├── nofocuspause/             自研：禁用失焦暂停
│   │   ├── ModTheSpire.json
│   │   └── src/nofocuspause/NoFocusPause.java
│   └── achievementenabler/       自研：解除 mod 模式成就限制
│       ├── ModTheSpire.json
│       └── src/achievementenabler/AchievementEnabler.java
├── scripts/
│   ├── launch_sts_bot.ps1        一键启动（含 Steam 工坊进程卡死处理）
│   ├── make_shortcut.ps1         生成桌面快捷方式
│   └── build_mods.ps1            从源码编译两个自制 Mod
├── config/
│   ├── CommunicationMod.properties   驱动挂载配置样例
│   └── mod_order.xml                 Mod 勾选列表样例
├── dist/
│   ├── NoFocusPause.jar          编译好的 Mod（可直接使用）
│   └── AchievementEnabler.jar
└── docs/
    ├── ARCHITECTURE.md           决策引擎设计细节
    ├── TROUBLESHOOTING.md        踩坑记录（强烈建议阅读）
    └── STEAM.md                  Steam 时长/成就集成说明
```

---

## 四、安装（从零复现）

### 前置要求

- Windows + **Steam 正版《杀戮尖塔》**（本项目所有验证基于 Steam 版 2022-12-20 构建）
- Python 3.8+（驱动只依赖标准库）
- 若要自己编译 Mod：JDK 8 + Maven（或用 `scripts/build_mods.ps1`）

### 1. 安装 Mod 加载器三件套

游戏目录（下称 `$GAME`，默认 `D:\Steam\steamapps\common\SlayTheSpire`）需要：

| 组件 | 版本要求 | 说明 |
|---|---|---|
| ModTheSpire | **3.22+**（推荐 3.30.x）| 必须从源码构建（GitHub release 只到 2018 年的 3.6.3，**与现代游戏不兼容**）|
| BaseMod | **5.36+**（推荐 5.56.x）| 同上，旧版 release（5.5.0）会报 `NoSuchMethodException` |
| CommunicationMod | 1.2.1+ | 放在 `$GAME/mods/` |
| 自制 Mod | 见 `dist/` | 放在 `$GAME/mods/` |

> ⚠️ **最大的坑**：GitHub 上 ModTheSpire/BaseMod 的 release 是 2018 年的老版本，与现在的游戏（2022 构建）不兼容，表现为补丁失败、游戏无法启动。正确做法是从源码构建最新版。细节见 `docs/TROUBLESHOOTING.md`。

### 2. 部署自制 Mod

把 `dist/NoFocusPause.jar` 和 `dist/AchievementEnabler.jar` 复制到 `$GAME/mods/`。
（或运行 `scripts/build_mods.ps1` 自行编译）

### 3. 配置 CommunicationMod

创建 `%LOCALAPPDATA%\ModTheSpire\CommunicationMod\config.properties`（样例见 `config/`）：

```properties
command=D\:\\Python311\\python.exe -X utf8 D\:\\path\\to\\driver.py
runAtGameStart=true
verbose=true
maxInitializationTimeout=30
```

`runAtGameStart=true` 让游戏启动时自动拉起驱动进程。

### 4. Steam 集成（可选但推荐）

在 `$GAME` 下创建 `steam_appid.txt`，内容为 `646570`。这样即使不通过 Steam 启动，游戏的 Steamworks 也能连上客户端，**时长与成就才会被记录**。详见 `docs/STEAM.md`。

### 5. 启动

```
powershell -ExecutionPolicy Bypass -File scripts/launch_sts_bot.ps1
```

或用 `scripts/make_shortcut.ps1` 生成桌面快捷方式（一键启动）。

---

## 五、使用

### 日常使用

双击桌面快捷方式即可。启动脚本会：
1. 用游戏自带 JRE 启动 ModTheSpire（`--mods basemod,CommunicationMod,nofocuspause,achievementenabler --skip-intro`）
2. 检测 MTS 的 Steam 创意工坊子进程（它可能卡住导致游戏起不来）并在其输出完成后结束它
3. 游戏加载后自动点"继续游戏"或开新局，驱动接管

### 手动接管

游戏运行时，向 `driver/manual_cmd.txt` 写入一条指令（一行），驱动会执行该指令一次并删除文件：

| 指令 | 含义 |
|---|---|
| `PLAY 3 0` | 打出第 3 张手牌，目标为 0 号敌人 |
| `PLAY 2` | 打出第 2 张牌（无目标牌）|
| `END` | 结束回合 |
| `CHOOSE 1` | 选择选项 2（0 起算）|
| `POTION use 0` | 使用第 1 瓶药水 |
| `PROCEED` / `RETURN` | 确认 / 取消（离开）|

### 模式切换

`driver/mode.txt`：
- `continue`（默认）：主菜单优先点"继续游戏"
- `new`：强制开新局

### 手动启动（调试用）

```
cd $GAME
jre\bin\java.exe -jar ModTheSpire.jar --mods basemod,CommunicationMod,nofocuspause,achievementenabler --skip-intro
```

---

## 六、决策引擎设计（简述）

决策引擎对每个状态只决定"下一步动作"，分层优先级如下：

| 层级 | 逻辑 |
|---|---|
| **斩杀** | 计算总伤害能否击杀某敌 → 优先击杀（减员=减伤）|
| **药水** | 29 种药水统一估值（伤害/减伤/血量/资源折算价值分），按场面与血量门槛择机使用 |
| **易伤/虚弱** | Boss/精英战保持易伤覆盖（伤害 ×1.5）；大攻击前上虚弱 |
| **格挡** | 按怪物意图计算总来袭伤害，扣除已有格挡后决定是否需要防御（Boss 阈值最严）|
| **能力牌** | 安全回合优先铺能力（恶魔形态/金属化等）|
| **攻击** | 最大伤害攻击，避免打在高格挡目标上；史莱姆王分裂阶段优先群伤 |
| **选卡** | 卡牌强度表 + 构筑倾向加成（力量流/毒流/幻影刃流/消耗流）+ 遗物联动 + 当前幕 Boss 针对性 |
| **路线** | 用完整地图做 6 层 beam 搜索，整条路径打分（血量越低越偏好篝火、避开精英）|
| **篝火** | 休息价值（实际回血量，防溢出）vs 锻造价值（未升级核心卡数量）加权决策 |
| **商店** | 删卡 > 遗物 > 卡牌（按幕动态门槛）> 药水；保留金币底线 |
| **事件** | 关键词加权（偏好"获得/最大生命/金币"，规避"失去/诅咒"）|

详细实现说明见 `docs/ARCHITECTURE.md`。

---

## 七、踩坑记录（重要）

本项目在调试过程中修复了大量问题，**强烈建议阅读 `docs/TROUBLESHOOTING.md`**，其中包括：

- Mod 版本兼容性（2018 release vs 现代游戏）
- CommunicationMod 的输入编码是 **GBK** 而非 UTF-8（中文文本会全部损坏）
- 主菜单状态只发送一次导致驱动死锁（已打补丁）
- 连上 Steam 后 MTS 的工坊子进程卡死导致游戏无法启动
- 游戏失焦自动暂停
- mod 模式成就被拦截的真实机制（`UnlockTracker.unlockAchiever` 的 `Settings.isModded` 判断）
- 决策引擎自身的多个 bug（格挡筛选误杀被减益防御牌、奖励界面死循环、崩溃保护等）

---

## 八、免责声明

- 本项目仅用于**个人学习**与自动化技术研究，请勿用于商业用途。
- `AchievementEnabler` 会解除游戏在 mod 模式下的成就限制，这属于开发者有意设置的约束，使用与否请自行判断。
- 所有代码按"现状"提供，不保证适用于其他游戏版本。

---

## 九、致谢

- [ModTheSpire](https://github.com/kiooeht/ModTheSpire) / [BaseMod](https://github.com/daviscook477/BaseMod) / [CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)
- [spirecomm](https://github.com/ForgottenArbiter/spirecomm)（协议与数据结构参考）
- Mega Crit（《杀戮尖塔》）
