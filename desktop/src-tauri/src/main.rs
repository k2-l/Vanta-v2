// 生产窗口禁用控制台窗口（Windows）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    vanta_desktop_lib::run();
}
