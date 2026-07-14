/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "/",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // 프론트/백엔드 분리 이후로는 `src/api/client.ts`의 `API_BASE_URL`이 API
  // 호출마다 백엔드 origin을 명시적으로 붙이므로(기본값
  // `http://localhost:8000`), dev server가 경로별로 프록시할 필요가 없다.
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
