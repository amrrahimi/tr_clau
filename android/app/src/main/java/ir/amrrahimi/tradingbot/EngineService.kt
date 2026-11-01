package ir.amrrahimi.tradingbot

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * Runs the bot's engine (the same Python backend as the desktop app) in the background.
 *
 * A foreground service with a notification that is always shown: Android keeps it running
 * while the screen is off or the app is closed. A partial wake lock keeps the CPU awake, so
 * the scans and the price checks of open positions keep going. The notification shows the
 * account; opened and closed trades get their own notifications.
 */
class EngineService : Service() {

    companion object {
        const val ACTION_STOP = "ir.amrrahimi.tradingbot.STOP"
        const val ENGINE = "http://127.0.0.1:8765"
        private const val CHANNEL_ENGINE = "engine"
        private const val CHANNEL_TRADES = "trades"
        private const val ID_ENGINE = 1
        private const val STATUS_EVERY_MS = 30_000L
        @Volatile private var started = false

        fun start(context: Context) {
            val intent = Intent(context, EngineService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent)
            else context.startService(intent)
        }
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private var lastEventTime = 0.0
    private var tradeNotificationId = 100

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            // Python cannot be stopped inside a running process: the whole app process ends.
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
            android.os.Process.killProcess(android.os.Process.myPid())
            return START_NOT_STICKY
        }
        makeChannels()
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, ID_ENGINE, engineNotification(getString(R.string.engine_running)), type)
        if (!started) {
            started = true
            val power = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "TradingBot:engine").apply {
                setReferenceCounted(false)
                acquire()
            }
            thread(name = "engine", isDaemon = true) { runEngine() }
            thread(name = "engine-status", isDaemon = true) { watchStatus() }
        }
        return START_STICKY   // if Android ever kills it, start it again
    }

    private fun runEngine() {
        try {
            val web = File(filesDir, "web")
            Log.i("TradingBot", "copying the screen")
            copyScreen(web)
            Log.i("TradingBot", "starting Python")
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            val data = File(filesDir, "trading-bot")
            Log.i("TradingBot", "starting the engine")
            // Blocks for as long as the engine runs.
            Python.getInstance().getModule("android_main").callAttr("run", data.absolutePath, web.absolutePath)
        } catch (error: Throwable) {
            Log.e("TradingBot", "engine stopped", error)
            update("موتور متوقف شد: ${error.message?.take(120)}")
        }
    }

    /** The built screen ships inside the app (assets/web); the engine serves it from a normal folder. */
    private fun copyScreen(target: File) {
        val version = packageManager.getPackageInfo(packageName, 0).lastUpdateTime.toString()
        val stamp = File(target, ".version")
        if (stamp.exists() && stamp.readText() == version) return
        target.deleteRecursively()
        fun copy(path: String, into: File) {
            val children = assets.list(path) ?: emptyArray()
            if (children.isEmpty()) {
                into.parentFile?.mkdirs()
                assets.open(path).use { input -> into.outputStream().use { input.copyTo(it) } }
            } else {
                into.mkdirs()
                for (child in children) copy("$path/$child", File(into, child))
            }
        }
        copy("web", target)
        stamp.writeText(version)
    }

    /** Every half minute: the account in the notification, and a notification per opened or closed trade. */
    private fun watchStatus() {
        while (true) {
            Thread.sleep(STATUS_EVERY_MS)
            try {
                val state = JSONObject(get("$ENGINE/api/paper"))
                val status = when (state.optString("status")) {
                    "running" -> "روشن"
                    "halted" -> "متوقف (افت زیاد)"
                    else -> "خاموش"
                }
                val equity = state.optDouble("equity")
                val open = state.optJSONArray("positions")?.length() ?: 0
                update("ربات $status · موجودی ${"%.2f".format(equity)} USDT · $open پوزیشن باز")
                tradeNotifications(state)
            } catch (_: Exception) {
                // the engine is still starting, or busy: try again next time
            }
        }
    }

    private fun tradeNotifications(state: JSONObject) {
        val events = state.optJSONArray("events") ?: return   // newest first
        var newest = lastEventTime
        for (i in events.length() - 1 downTo 0) {
            val e = events.getJSONObject(i)
            val time = e.optDouble("time")
            if (time <= lastEventTime) continue
            newest = maxOf(newest, time)
            if (lastEventTime == 0.0) continue   // first look after a start: no notifications for old events
            val coin = e.optString("symbol")
            val text = when (e.optString("kind")) {
                "open" -> "باز شد: $coin ${if (e.optString("side") == "long") "خرید" else "فروش"} · ${e.optString("timeframe")} · ${e.optString("strategy")}"
                "close" -> "بسته شد: $coin · نتیجه ${"%+.2f".format(e.optDouble("pnl"))} USDT"
                "halted" -> "ربات به خاطر افت زیاد متوقف شد"
                else -> null
            } ?: continue
            val manager = getSystemService(NotificationManager::class.java)
            manager.notify(tradeNotificationId++, NotificationCompat.Builder(this, CHANNEL_TRADES)
                .setSmallIcon(R.drawable.ic_bot)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(text)
                .setContentIntent(openApp())
                .setAutoCancel(true)
                .build())
        }
        lastEventTime = if (lastEventTime == 0.0) maxOf(newest, 1.0) else newest
    }

    private fun get(url: String): String {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 5_000
        connection.readTimeout = 10_000
        return try {
            connection.inputStream.bufferedReader().readText()
        } finally {
            connection.disconnect()
        }
    }

    private fun update(text: String) {
        getSystemService(NotificationManager::class.java).notify(ID_ENGINE, engineNotification(text))
    }

    private fun openApp(): PendingIntent = PendingIntent.getActivity(
        this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    private fun engineNotification(text: String): Notification {
        val stop = PendingIntent.getService(
            this, 1, Intent(this, EngineService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL_ENGINE)
            .setSmallIcon(R.drawable.ic_bot)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openApp())
            .addAction(0, getString(R.string.stop), stop)
            .build()
    }

    private fun makeChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ENGINE, getString(R.string.channel_engine), NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_TRADES, getString(R.string.channel_trades), NotificationManager.IMPORTANCE_DEFAULT))
    }

    override fun onDestroy() {
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }
}
