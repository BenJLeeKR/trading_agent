/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  server: {
    proxy: {
      "/health": "http://localhost:8000",
      "/health/readyz": "http://localhost:8000",
      "/orders": "http://localhost:8000",
      "/reconciliation": "http://localhost:8000",
      "/audit-logs": "http://localhost:8000",
      "/accounts": "http://localhost:8000",
      "/positions": "http://localhost:8000",
      "/cash-balances": "http://localhost:8000",
      "/clients": "http://localhost:8000",
      "/instruments": "http://localhost:8000",
      "/trade-decisions": "http://localhost:8000",
      "/decision-contexts": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/__tests__/setup.ts",
    css: true,
    include: ["src/__tests__/**/*.test.{ts,tsx}"],
  },
});
