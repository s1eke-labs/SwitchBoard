import { defineConfig } from "vite";
import type { ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import { Agent as HttpAgent } from "node:http";
import path from "node:path";

const apiProxyAgent = new HttpAgent({
  keepAlive: true,
});

const apiProxy: Record<string, ProxyOptions> = {
  "/api": {
    target: "http://127.0.0.1:8080",
    agent: apiProxyAgent,
  },
};

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react-dom")) {
            return "react-dom";
          }
          if (id.includes("node_modules/react")) {
            return "react";
          }
          if (id.includes("node_modules/@tanstack/react-query")) {
            return "query";
          }
          if (id.includes("node_modules/recharts")) {
            return "charts";
          }
          return undefined;
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    proxy: apiProxy,
  },
});
