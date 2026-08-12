import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom"],
          "vendor-md": ["react-markdown", "remark-gfm"],
          "vendor-ui": ["lucide-react", "zustand", "@microsoft/fetch-event-source"],
        },
      },
    },
  },
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react-dom/client",
      "react-markdown",
      "remark-gfm",
      "zustand",
      "@microsoft/fetch-event-source",
      "lucide-react",
    ],
  },
  server: {
    // 本地开发直连：对齐 harness CORS 放行的 5173；HMR 用默认本地 ws（原 wss/5173 是 hk 远端 nginx 反代配置，已随 hk 退役）
    port: 5173,
    strictPort: true,
    warmup: {
      clientFiles: [
        "./src/main.tsx",
        "./src/app/App.tsx",
        "./src/features/chat/components/MessageList.tsx",
        "./src/app/NavSidebar.tsx",
        "./src/features/chat/components/ChatInput.tsx",
        "./src/shared/lib/api.ts",
        "./src/shared/lib/sse.ts",
        "./src/store/chat.ts",
        "./src/store/auth.ts",
      ],
    },
  },
  preview: {
    port: 5173,
    strictPort: true,
    host: "0.0.0.0",
  },
});
