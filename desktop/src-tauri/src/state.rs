//! 应用共享状态——由 Tauri `manage` 持有，命令通过 `State` 访问。

use crate::connections::ConnectionStore;

pub struct AppState {
    pub connections: ConnectionStore,
}

impl AppState {
    pub fn new(connections: ConnectionStore) -> Self {
        Self { connections }
    }
}
