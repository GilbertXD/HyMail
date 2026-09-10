use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::Serialize;
use tauri::Manager;
use uuid::Uuid;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ApiConfig {
    base_url: String,
    token: String,
}

struct SidecarState {
    child: Mutex<Option<Child>>,
    config: ApiConfig,
}

#[tauri::command]
fn get_api_config(state: tauri::State<'_, SidecarState>) -> ApiConfig {
    state.config.clone()
}

fn pick_port() -> u16 {
    let listener =
        TcpListener::bind("127.0.0.1:0").expect("failed to bind loopback port");
    listener
        .local_addr()
        .expect("failed to read loopback address")
        .port()
}

fn spawn_sidecar(port: u16, token: &str) -> Child {
    let api_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("api");
    let port_text = port.to_string();

    Command::new("uv")
        .args([
            "run",
            "uvicorn",
            "hymail_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &port_text,
        ])
        .current_dir(api_dir)
        .env("HYMAIL_API_TOKEN", token)
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("failed to start HyMail API sidecar")
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let port = pick_port();
    let token = Uuid::new_v4().to_string();
    let config = ApiConfig {
        base_url: format!("http://127.0.0.1:{port}"),
        token: token.clone(),
    };
    let child = spawn_sidecar(port, &token);

    tauri::Builder::default()
        .manage(SidecarState {
            child: Mutex::new(Some(child)),
            config,
        })
        .invoke_handler(tauri::generate_handler![get_api_config])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.app_handle().state::<SidecarState>();
                let mut guard = match state.child.lock() {
                    Ok(guard) => guard,
                    Err(_) => return,
                };
                if let Some(child) = guard.as_mut() {
                    let _ = child.kill();
                }
                *guard = None;
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}