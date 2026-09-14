import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 前端开发服务器；生产构建为静态文件，由前端容器用 vite preview 提供。
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  preview: { host: true, port: 5173 },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
