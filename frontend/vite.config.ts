/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/hook": "http://localhost:8000",
      "/mock": "http://localhost:8000",
    },
  },
  test: {
    // Only unit tests live in src/; e2e/ holds Playwright specs (run via
    // `npm run e2e`, not vitest).
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
    css: false,
  },
});
