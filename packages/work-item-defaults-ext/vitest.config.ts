import { defineConfig } from "vitest/config";

// Pure functions only — no DOM, so no jsdom and no react plugin.
export default defineConfig({
  test: {
    include: ["src/__tests__/**/*.test.ts"],
  },
});
