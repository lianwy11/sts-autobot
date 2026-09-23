package nofocuspause;

import com.evacipated.cardcrawl.modthespire.lib.SpireInitializer;
import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpireReturn;
import com.megacrit.cardcrawl.core.CardCrawlGame;

// Keeps the game simulating while the window is not focused, so an external
// driver (CommunicationMod bots) can play without holding the foreground.
@SpireInitializer
public class NoFocusPause {
    public static void initialize() {
    }

    @SpirePatch(clz = CardCrawlGame.class, method = "pause")
    public static class PausePatch {
        public static SpireReturn<Void> Prefix(CardCrawlGame __instance) {
            return SpireReturn.Return(null);
        }
    }
}
