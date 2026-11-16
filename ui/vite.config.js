// 由 gateway 在 /ui/ 提供；不載入任何遠端資源（Phase 8.5）。
// Served by the gateway under /ui/; no remote resources (Phase 8.5).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",  // 相對路徑：gateway 的 /ui/ 與 Tauri 共用 / relative: shared by /ui/ and Tauri
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
});
