/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    setupFiles: ["src/vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary", "html"],
      reportsDirectory: "coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.ts",
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/vite-env.d.ts",
        "src/i18n/locales/**",
        "src/types.ts",
        "src/auth/types.ts",
        "src/shared-contract.d.ts",
      ],
      thresholds: {
        lines: 95,
        functions: 94,
        branches: 85,
        statements: 95,
      },
    },
  },
  resolve: {
    alias: {
      "@shared": path.resolve(__dirname, "../backend/shared"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes("node_modules/react-markdown") ||
            id.includes("node_modules/remark") ||
            id.includes("node_modules/micromark") ||
            id.includes("node_modules/unified") ||
            id.includes("node_modules/mdast") ||
            id.includes("node_modules/hast")
          ) {
            return "markdown";
          }
          if (
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react/")
          ) {
            return "vendor";
          }
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        timeout: 3_600_000,
      },
    },
  },
});
