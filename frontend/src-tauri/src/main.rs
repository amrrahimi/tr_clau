// The desktop window. Its only extra job: start the Python backend when the
// app opens and stop it when the app closes.

// On Windows, don't open an extra console window next to the app.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

/// The running backend, kept so it can be stopped on exit.
struct Backend(Mutex<Option<CommandChild>>);

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
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
