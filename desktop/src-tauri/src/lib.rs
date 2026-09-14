//! Vanta 桌面 Tauri Core 入口。
//!
//! 职责边界（方案 §5.1）：Rust 只做桌面安全边界、连接与凭据管理、事件转发，
//! 不解释 Agent 决策；后端才是运行状态的权威来源。

mod backend_gateway;
mod commands;
mod connections;
mod credentials;
mod diagnostics;
mod error;
mod state;

use connections::ConnectionStore;
use state::AppState;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            // connection profile 落 app data 目录（非敏感；凭据在钥匙串）。
            let dir = app
                .path()
                .app_data_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."));
            let store = ConnectionStore::load(dir.join("connections.json"));
            app.manage(AppState::new(store));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::connection_list,
            commands::connection_save,
            commands::connection_delete,
            commands::connection_test,
            commands::connection_activate,
            commands::auth_login,
            commands::auth_logout,
            commands::api_request,
            commands::chat_start,
            commands::run_subscribe,
            commands::stream_stop,
            commands::artifact_export,
            commands::diagnostics_export,
            commands::app_check_update,
        ])
        .run(tauri::generate_context!())
        .expect("启动 Vanta 桌面失败");
}
