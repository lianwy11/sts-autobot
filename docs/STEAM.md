# Steam 集成：时长记录与成就解锁

## 1. 为什么直接启动游戏不记录时长/成就

用 `java.exe -jar ModTheSpire.jar` 直接启动时，游戏进程与 Steam 没有任何关联：

- Steam 只统计"它自己启动的进程"，或通过 Steamworks API 主动上报的会话
- 游戏日志会明确报错：
  ```
  Could not connect to Steam. Is it running?
  [FAILURE] Steam API failed to initialize correctly.
  ```
- 结果：Steam 的"最后游玩时间"纹丝不动（实测停留在上一次通过 Steam 启动的时间），成就也不会解锁

**验证方法**：查看 Steam 应用清单 `steamapps\appmanifest_646570.acf` 里的 `LastPlayed` 时间戳，或检查游戏日志里的 Steam 初始化结果。

## 2. 修复：steam_appid.txt

在游戏根目录创建 `steam_appid.txt`，内容为 AppID：

```
646570
```

原理：Steamworks 初始化需要知道"自己是哪个 App"。通过 Steam 启动时由启动上下文提供；脱离 Steam 启动时则读取工作目录下的 `steam_appid.txt`。

**最小化验证**（不需要启动游戏）：

```java
import com.codedisaster.steamworks.SteamAPI;
public class TestSteam {
    public static void main(String[] a) {
        SteamAPI.loadLibraries();
        System.out.println(SteamAPI.init() ? "STEAM INIT: SUCCESS" : "STEAM INIT: FAILED");
    }
}
```
```
cd $GAME
jre\bin\java.exe -cp "desktop-1.0.jar;<编译输出目录>" TestSteam
```

- 无 `steam_appid.txt` → `STEAM INIT: FAILED`（复现故障）
- 有 `steam_appid.txt` → `STEAM INIT: SUCCESS`

修复生效后：
- 游戏日志出现 `[SUCCESS] Steam API initialized successfully.`
- 游戏进程加载 `steam_api64.dll` / `steamworks4j64.dll` / **`steamclient64.dll`**（后者说明与 Steam 客户端建立了连接）
- Steam 清单的 `LastPlayed` 开始实时刷新 → **游玩时长已记录**

### 副作用警告

连上 Steam 后，ModTheSpire 会启动 `SteamWorkshop` 子进程查询创意工坊——它可能**打完信息后卡住不退出**，而 MTS 在等它的 stdout EOF，导致游戏永远起不来。启动脚本会检测并结束该进程（详见 `docs/TROUBLESHOOTING.md` C2）。

## 3. 成就：游戏在 mod 模式下主动拦截

### 3.1 拦截点（反编译 `UnlockTracker.unlockAchievement` 得到）

```java
public static void unlockAchievement(String key) {
    if (Settings.isModded || Settings.isShowBuild || !Settings.isStandardRun()) {
        return;           // ← mod 模式下直接返回，成就被丢弃
    }
    CardCrawlGame.publisherIntegration.unlockAchievement(key);
    achievementPref.putBoolean(key, true);   // 本地记录
    ...
}
```

这是开发者的有意设计（成就应在"公平环境"下获得），**任何 mod 加载后 `Settings.isModded` 都为 true**，因此 mod 模式下一律不解锁成就。

### 3.2 本项目的解法：AchievementEnabler

自研 Mod（源码见 `mods/achievementenabler/`）：在游戏调用 `unlockAchievement` 的瞬间临时清掉 `isModded`，让游戏走完自己的成就流程（含 Steam 上报与本地记录），调用结束立刻还原：

```java
@SpirePatch(clz = UnlockTracker.class, method = "unlockAchievement")
public static class EnablerPatch {
    public static SpireReturn<Void> Prefix(String key) {
        if (Settings.isModded) {
            Settings.isModded = false;
            try {
                UnlockTracker.unlockAchievement(key);   // 递归调用，此时守卫通过
            } finally {
                Settings.isModded = true;               // 立刻还原，不影响其他逻辑
            }
            return SpireReturn.Return(null);
        }
        return SpireReturn.Continue();
    }
}
```

**保留的限制**：`isStandardRun()` 检查未改动，因此每日挑战/自定义/种子局依然不会解锁成就（与原版一致）。`isShowBuild` 同理。

### 3.3 验证清单

| 检查项 | 命令/位置 | 期望 |
|---|---|---|
| Mod 已加载 | 游戏日志 Mod list | `- achievementenabler (1.0.0)` |
| 补丁无错误 | 日志 `Finding patches...` 段 | 无 `NoSuchMethodException` 之类报错 |
| mod 状态确认 | 日志 | `Counting modded unlocks`（证明 `isModded=true`，补丁会生效）|
| Steam 连接 | 日志 | `[SUCCESS] Steam API initialized successfully.` |
| 成就触发 | 日志 | `Achievement Unlocked: <名称>` |
| 本地成就记录 | `preferences/STSAchievements` | 触发后 JSON 出现对应键 |

> 注：成就需要特定条件（通关角色、进阶等级、花式挑战等）。击败第一幕 Boss 本身不是成就，别误判为"没生效"。

## 4. 已知边界

- 本方案针对 **Steam 版**（AppID 646570）。GOG/WeGame 版有各自的集成实现（`GogIntegration` / `WeGameIntegration`），本项目未覆盖。
- 若 Steam 未运行，`steam_appid.txt` 存在与否都不会连上——此时不影响单机游玩，只是不记录。
- 成就解锁依赖 Steam 客户端处于登录状态。
