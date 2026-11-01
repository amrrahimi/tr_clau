#!/usr/bin/env bash
# Run by CI on an Android emulator: install the app, start it, and check that the engine answers,
# serves the screen and runs as a foreground service. Prints the app's log either way.
set -u
APK=android/app/build/outputs/apk/release/app-release.apk
PKG=ir.amrrahimi.tradingbot
adb install -r "$APK"
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS || true
adb shell am start -n $PKG/.MainActivity
adb forward tcp:8765 tcp:8765
ok=0
for i in $(seq 1 150); do
  if curl -sf http://127.0.0.1:8765/api/health; then ok=1; break; fi
  sleep 2
done
echo
echo "engine answered: $ok"
adb logcat -d | grep -a -i -E "tradingbot|python\.|FATAL" | tail -80
[ "$ok" = 1 ] || exit 1
fail=0
curl -sf http://127.0.0.1:8765/ | grep -q '<div id="app">' && echo "screen: served" || { echo "screen: MISSING"; fail=1; }
curl -sf http://127.0.0.1:8765/api/paper | grep -q '"status"' && echo "bot state: ok" || { echo "bot state: MISSING"; fail=1; }
curl -sf http://127.0.0.1:8765/api/connection; echo
# Opening the exchange connection loads ccxt with cryptography/cffi (native libraries). A missing
# library shows up only here ("Could not start the exchange connection"), not in the health check.
markets=$(curl -s "http://127.0.0.1:8765/api/markets?market_type=futures")
if echo "$markets" | grep -q "Could not start the exchange connection"; then
  echo "exchange connection: FAILED TO START: $markets"; fail=1
else
  echo "exchange connection: started (${markets:0:120})"
fi
adb shell dumpsys activity services $PKG/.EngineService | grep -q "isForeground=true" \
  && echo "service: in the foreground" || { echo "service: NOT foreground"; fail=1; }
# Background: leave the app (home screen), wait, the engine must still answer.
adb shell input keyevent KEYCODE_HOME
sleep 20
curl -sf http://127.0.0.1:8765/api/health > /dev/null && echo "after leaving the app: still answering" \
  || { echo "after leaving the app: NOT answering"; fail=1; }
[ "$fail" = 0 ] && echo "::notice title=Emulator (Android 14)::engine started, screen served, foreground service, still running in the background"
exit $fail
