//! 应用共享状态——由 Tauri `manage` 持有，命令通过 `State` 访问。

use crate::connections::ConnectionStore;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tokio::sync::oneshot;

#[derive(Clone, Default)]
pub struct StreamRegistry {
    inner: Arc<Mutex<HashMap<String, oneshot::Sender<()>>>>,
}

impl StreamRegistry {
    pub fn insert(&self, id: String, cancel: oneshot::Sender<()>) {
        self.inner.lock().expect("stream registry poisoned").insert(id, cancel);
    }

    pub fn remove(&self, id: &str) -> Option<oneshot::Sender<()>> {
        self.inner.lock().expect("stream registry poisoned").remove(id)
    }
}

pub struct AppState {
    pub connections: ConnectionStore,
    pub streams: StreamRegistry,
}

impl AppState {
    pub fn new(connections: ConnectionStore) -> Self {
        Self { connections, streams: StreamRegistry::default() }
    }
}
