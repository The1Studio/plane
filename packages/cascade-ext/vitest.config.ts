import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// React component tests (the confirm modal's focus + Enter behavior) need a real DOM and JSX
// transform — jsdom + @vitejs/plugin-react, the standard Vitest pairing for this. `jsdom` is
// pinned to the exact version already resolved for `vitest@4` elsewhere in this monorepo's
// lockfile, so this isn't introducing an unproven combination.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/__tests__/**/*.test.ts", "src/__tests__/**/*.test.tsx"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
