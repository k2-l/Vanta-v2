//! IPC 命令 allowlist（方案 §8.2）——WebView 唯一可调用面。

mod api;
mod auth;
mod connection;
mod stream;
mod system;

pub use api::*;
pub use auth::*;
pub use connection::*;
pub use stream::*;
pub use system::*;
