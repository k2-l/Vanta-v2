import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Tauri 期望固定端口；HMR 端口与 dev server 分离，避免与 WebView 冲突。
const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Tauri CLI 期望这些配置：固定端口、不清屏、按平台构建目标。
  clearScreen: false,
  server: {
    port: 5180,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 5181,
        }
      : undefined,
    watch: {
      // Rust 侧由 tauri 自行监视，避免 vite 扫描。
      ignored: ["**/src-tauri/**"],
    },
  },
  // 生产构建：Tauri 使用 dist/，浏览器兜底 target 用现代 ES。
  build: {
    target: "es2022",
    sourcemap: !!process.env.TAURI_DEBUG,
    minify: process.env.TAURI_DEBUG ? false : "esbuild",
  },
});
