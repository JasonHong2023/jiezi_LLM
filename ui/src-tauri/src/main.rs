// 芥子桌面 App：只顯示前端，所有資料經本機 gateway（127.0.0.1:36100）；不註冊任何指令、不開放任何外掛（唯讀雛形）。
// Jiezi desktop app: shows the front end only; data goes through the local gateway; no commands, no plugins.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running the Jiezi desktop app");
}
