// The desktop window. Its only extra job: start the Python backend when the
// app opens and stop it when the app closes.

// On Windows, don't open an extra console window next to the app.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

/// The "see-through" background (owner 2026-11-09): the desktop shows behind the window, blurred by the
/// system (macOS vibrancy; Windows 11 Mica, else acrylic / blur). Only while the owner chose it, because
/// on some Windows versions these effects make dragging the window slow.
#[tauri::command]
fn set_glass(window: tauri::WebviewWindow, on: bool) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        use window_vibrancy::{apply_vibrancy, clear_vibrancy, NSVisualEffectMaterial};
        if on {
            apply_vibrancy(&window, NSVisualEffectMaterial::HudWindow, None, None).map_err(|e| e.to_string())?;
        } else {
            let _ = clear_vibrancy(&window);
        }
    }
    #[cfg(target_os = "windows")]
    {
        use window_vibrancy::{apply_acrylic, apply_blur, apply_mica, clear_acrylic, clear_blur, clear_mica};
        if on {
            if apply_mica(&window, Some(true)).is_err() && apply_acrylic(&window, Some((10, 14, 24, 90))).is_err() {
                apply_blur(&window, Some((10, 14, 24, 90))).map_err(|e| e.to_string())?;
            }
        } else {
            let _ = clear_mica(&window);
            let _ = clear_acrylic(&window);
            let _ = clear_blur(&window);
        }
    }
    let _ = (&window, on);
    Ok(())
}

/// The running backend, kept so it can be stopped on exit.
struct Backend(Mutex<Option<CommandChild>>);

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![set_glass])
        .setup(|app| {
            let (mut events, child) = app
                .shell()
                .sidecar("backend")?
                // Tells the backend to exit if this app disappears (see backend/run.py).
                .env("EXIT_WHEN_PARENT_CLOSES", "1")
                .spawn()?;

            // Read (and ignore) the backend's output. If nobody reads it,
            // the output pipe fills up and the backend freezes.
            tauri::async_runtime::spawn(async move { while events.recv().await.is_some() {} });

            app.manage(Backend(Mutex::new(Some(child))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to start the app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(child) = handle.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
