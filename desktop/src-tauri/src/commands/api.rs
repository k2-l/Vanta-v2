//! 通用受控 API 命令——只接受 ApiOperation 枚举，不接受任意 method+URL（方案 §8.2）。

use crate::backend_gateway::{self, ApiOperation};
use crate::error::CmdResult;
use crate::state::AppState;
use tauri::State;

#[tauri::command]
pub async fn api_request(
    state: State<'_, AppState>,
    connection_id: String,
    operation: ApiOperation,
) -> CmdResult<serde_json::Value> {
    backend_gateway::request(&state.connections, &connection_id, operation).await
}
