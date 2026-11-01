package ir.amrrahimi.tradingbot

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** The screen: the same interface as the desktop app, served by the engine on the phone. */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var waiting: TextView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()   // links stay inside the app
            setBackgroundColor(0xFF131722.toInt())
        }
        waiting = TextView(this).apply {
            text = getString(R.string.starting)
            setTextColor(0xFFD1D4DC.toInt())
            textSize = 16f
            gravity = Gravity.CENTER
            setBackgroundColor(0xFF131722.toInt())
        }
        setContentView(FrameLayout(this).apply {
            addView(web)
            addView(waiting)
        })
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else moveTaskToBack(true)   // the engine keeps running
            }
        })

        askForNotifications()
        EngineService.start(this)
        askToIgnoreBatteryOptimization()
        openWhenReady()
    }

    /** The engine needs a few seconds to start (Python, then the server); the page opens when it answers. */
    private fun openWhenReady() {
        thread(isDaemon = true) {
            repeat(180) {
                if (answers("${EngineService.ENGINE}/api/health")) {
                    runOnUiThread {
                        web.loadUrl("${EngineService.ENGINE}/")
                        waiting.animate().alpha(0f).withEndAction { waiting.visibility = TextView.GONE }
                    }
                    return@thread
                }
                Thread.sleep(1_000)
            }
            runOnUiThread { waiting.text = "موتور ربات روشن نشد. برنامه را ببندید و دوباره باز کنید." }
        }
    }

    private fun answers(url: String): Boolean = try {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 1_000
        connection.readTimeout = 2_000
        val ok = connection.responseCode == 200
        connection.disconnect()
        ok
    } catch (_: Exception) {
        false
    }

    private fun askForNotifications() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    /** Without this, many phones stop background apps after a while to save battery. Asked once. */
    @SuppressLint("BatteryLife")
    private fun askToIgnoreBatteryOptimization() {
        val power = getSystemService(PowerManager::class.java)
        val prefs = getSharedPreferences("app", MODE_PRIVATE)
        if (power.isIgnoringBatteryOptimizations(packageName) || prefs.getBoolean("askedBattery", false)) return
        prefs.edit().putBoolean("askedBattery", true).apply()
        Toast.makeText(this, R.string.battery_hint, Toast.LENGTH_LONG).show()
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (_: Exception) {
            // some phones do not have this screen
        }
    }
}
