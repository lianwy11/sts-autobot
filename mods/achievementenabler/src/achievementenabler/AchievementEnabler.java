package achievementenabler;

import com.evacipated.cardcrawl.modthespire.lib.SpireInitializer;
import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpireReturn;
import com.megacrit.cardcrawl.core.Settings;
import com.megacrit.cardcrawl.unlock.UnlockTracker;

// Slay the Spire's UnlockTracker.unlockAchievement() bails out early when
// Settings.isModded is set, which is why modded runs earn no achievements.
// This patch clears that flag just for the duration of the call, so the game's
// own achievement bookkeeping still runs. Daily/custom/seeded runs remain
// blocked by the untouched isStandardRun() check inside the original method.
@SpireInitializer
public class AchievementEnabler {
    public static void initialize() {
    }

    @SpirePatch(clz = UnlockTracker.class, method = "unlockAchievement")
    public static class EnablerPatch {
        public static SpireReturn<Void> Prefix(String key) {
            if (Settings.isModded) {
                Settings.isModded = false;
                try {
                    UnlockTracker.unlockAchievement(key);
                } finally {
                    Settings.isModded = true;
                }
                return SpireReturn.Return(null);
            }
            return SpireReturn.Continue();
        }
    }
}
