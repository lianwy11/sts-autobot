# 踩坑记录（Troubleshooting）

按"现象 → 原因 → 解决"整理。这些坑绝大多数会直接导致游戏起不来或机器人行为异常，建议全读。

---

## A. 环境与 Mod 兼容性

### A1. Mod 补丁失败：`NoSuchMethodException: Patch basemod...ForceUnlock`

**现象**：ModTheSpire 加载 BaseMod 时报
```
java.lang.NoSuchMethodException: Patch basemod.patches...DeathScreen.ForceUnlock:
No method named [calculateUnlockProgress] found on class [...DeathScreen]
```
游戏无法启动。

**原因**：GitHub 上 BaseMod 的 **release 版本停留在 2018 年（5.5.0）**，ModTheSpire 的 release 也停留在 2018（3.6.3），而现在的游戏是 2022 年构建，方法签名已变。现代版本（BaseMod 5.36+、MTS 3.22+）只通过 Steam 创意工坊分发。

**解决**：从源码构建最新版（本项目 `scripts/build_mods.ps1` 演示了流程）：
```
git clone ModTheSpire → mvn package → 得到 ModTheSpire.jar
git clone BaseMod     → mvn package → 得到 mods/BaseMod.jar
```
注意 BaseMod 源码含中文注释，构建需加 `-Dproject.build.sourceEncoding=UTF-8`（否则中文 Windows 下按 GBK 编译会报"未结束的字符文字"）。

> 提示：`ModTheSpire.jar` 只有 master 分支支持 `--mods a,b,c --skip-intro` 命令行参数（旧版只能弹 GUI 手动勾选）。

### A2. 匿名 steamcmd 无法下载创意工坊 Mod

**现象**：`steamcmd +login anonymous +workshop_download_item 646570 <id>` 报 `ERROR! Download item failed (No match)`。

**原因**：杀戮尖塔的创意工坊内容要求拥有游戏本体的账号，匿名账号无权限。

**解决**：从源码构建，或由你在 Steam 客户端手动订阅。

---

## B. 通信协议

### B1. 中文全部变成乱码 / 事件选择永远选第一个

**现象**：日志里中文显示为 `����`；事件选项、卡牌名匹配失效。

**原因**：CommunicationMod（Java）用**平台默认编码**写 stdin，简体中文 Windows 下是 **GBK**，而驱动按 UTF-8 解码。

**解决**：按字节读入，`utf-8 → gbk` 顺序尝试解码：
```python
def decode_in(raw):
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
```
（卡牌匹配用英文 `id` 字段不受影响，所以 bug 隐蔽了很久。）

### B2. 主菜单状态只发一次 → 驱动死锁

**现象**：点击"继续游戏"落空后（当时没有存档），Mod 不再发送任何状态，驱动傻等，游戏停在主菜单。

**原因**：`GameStateListener.checkForMenuStateChange()` 用一次性标志 `hasPresentedOutOfGameState`，菜单状态每次进入菜单只发一次。指令执行后不会再发新状态。

**解决**：给 CommunicationMod 打补丁，让菜单状态在每条指令执行后可重复发送：
```java
// checkForMenuStateChange 末尾追加：
if (CardCrawlGame.mode == CardCrawlGame.GameMode.CHAR_SELECT && CardCrawlGame.mainMenuScreen != null
        && !CommandExecutor.isInDungeon() && !waitingForCommand) {
    stateChange = true;
}
```
（本项目直接重编译 CommunicationMod；另需放开 `isInDungeon()` 对 click/key/wait 命令的限制——主菜单点"继续"按钮需要 CLICK 指令。）

### B3. 主菜单"继续游戏"按钮坐标

CommunicationMod 不提供"继续"命令，只能模拟点击。按钮布局从游戏字节码反推：
- `MenuButton.START_Y = 120×scale`、`SPACE_Y = 50×scale`，第 6 个按钮（index 6）为 RESUME_GAME
- 游戏坐标系原点在左下，CLICK 指令用左上原点的 1920×1080 虚拟坐标
- 换算结果：`CLICK LEFT 240 660`

### B4. 商店"离开"按钮不叫 return

不同版本的离开按钮文本不同（`proceed` / `return` / `leave`）。驱动应在 `available_commands` 里动态查找，不要硬编码。

### B5. 药水/商店选项的文本格式

| 界面 | 选项格式 |
|---|---|
| 卡牌奖励 | 卡名**小写**（中文卡名 toLowerCase 无变化）|
| 篝火 | 英文类名派生：`rest` / `smith` / `recall` / `dig` / `lift` / `toke` |
| 战斗奖励 | 英文枚举名小写：`gold` / `card` / `relic` / `potion` |
| 商店 | 卡名小写 + 遗物/药水原名；删卡为字面量 `purge` |

---

## C. 运行环境

### C1. 游戏窗口失焦即暂停，挂机中断

**现象**：切到别的窗口后机器人就不动了，日志出现 `PAUSE()`。

**原因**：LibGDX 在窗口失焦时回调 `CardCrawlGame.pause()`。

**解决**：自研 `NoFocusPause` Mod，`@SpirePatch` 拦截 `CardCrawlGame.pause()` 使其直接返回：
```java
@SpirePatch(clz = CardCrawlGame.class, method = "pause")
public static class PausePatch {
    public static SpireReturn<Void> Prefix(CardCrawlGame __instance) {
        return SpireReturn.Return(null);
    }
}
```
副作用：ESC 手动暂停也会失效（对挂机场景可接受）。

### C2. 连上 Steam 后游戏起不来（MTS 工坊子进程卡死）

**现象**：创建 `steam_appid.txt` 后 MTS 打印 `Searching for Workshop items...`，然后**永久卡住**，游戏再也起不来，一个 `SteamWorkshop` 子进程几乎零 CPU 挂着。

**原因**：`Loader.java` 里 MTS 启动子进程查询创意工坊，并 `while ((line = reader.readLine()) != null)` **无限等待其 stdout EOF**；该子进程打完信息后不退出。

**解决**：启动脚本在检测到 `SteamWorkshop` 进程后等待 ~10 秒（保证它已输出）再结束它，MTS 收到 EOF 即继续启动游戏。见 `scripts/launch_sts_bot.ps1`。

### C3. 进程用 javaw 启动后看不到日志

`javaw.exe` 无控制台。启动脚本用 `-RedirectStandardOutput` 把游戏输出重定向到 `game_out.log`，便于排查 Steam/成就问题。

---

## D. Steam 集成

见 `docs/STEAM.md`。核心两点：
1. 缺 `steam_appid.txt` → `[FAILURE] Steam API failed to initialize correctly.`，时长/成就都不记录
2. mod 模式下成就被 `UnlockTracker` 主动拦截 → 需要 `AchievementEnabler`

---

## E. 决策引擎自身的坑（都已修）

| 现象 | 原因 | 修复 |
|---|---|---|
| 战斗时**从不出防御牌**，被精英打死 | 格挡牌筛选条件写成"格挡 ≥5 才考虑"，而拉格瓦林"吸魂"减 1 敏捷后防御只剩 4 点，被整体过滤 | 阈值降为 3，必要时接受任意正格挡；并加"绝望防御"（预计致死则强制格挡）|
| 卡组永远没升级（锻造是假的）| 篝火决策逻辑正常，但选项匹配依赖的中文文本因编码问题损坏，`find()` 全部失败，永远回退到"选项 0"（休息）| 修复 GBK 解码（B1）|
| 画面频闪 | 奖励屏死循环：选"查看卡牌"→跳过后退回奖励屏→再选"查看卡牌"，每秒 45 次界面切换 | 奖励屏状态机（卡牌只开一次）+ 震荡检测 + 指令节流 0.1s |
| 商店进出无限乒乓 | 先判断了 `room_type == ShopRoom`，但地图界面也在同一个房间类型下，导致地图选择被当成商店离开 | 优先判断 `screen_type == MAP` |
| 打 240 血 Boss 每回合只输出 11 伤 | 选卡只看单卡强度，拿了大量 2.0 分平庸卡，卡组无伤害引擎 | 强化力量卡权重与升级优先级、加"稀释保护"（卡组越大越挑）、Boss 战保持易伤覆盖 |
| 残血撞怪物房致死 | 路线评分完全不看血量 | 血量 <25% 怪物房权重 -3，<40% 额外惩罚，商店同理 |
| 驱动静默死亡（游戏干等）| 决策函数抛异常没有兜底 | 主循环包裹 `try/except` 记录 `DECISION CRASH` 并跳过 |

---

## F. 调试技巧

1. **保留最后状态快照**：驱动把最新状态写到 `last_state.json`，排查字段名时直接读它，比猜快得多。
2. **看"每场战斗净失血"**：从日志按楼层/房间统计血量变化，能快速区分"战斗打得差"还是"路线/资源规划差"。
3. **怪物 ID 日志**：每次遇到新怪打一行 `fight: vs <id>(hp/max)`，便于针对特定怪物做特化。
4. **数值化决策日志**：篝火/地图/药水决策都记录评分（如 `campfire: rest 0.48 vs smith 0.51 -> smith`），便于复盘。
