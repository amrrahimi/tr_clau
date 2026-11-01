package ir.amrrahimi.tradingbot

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** After the phone restarts (or the app is updated), the engine starts again by itself. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            EngineService.start(context)
        }
    }
}
