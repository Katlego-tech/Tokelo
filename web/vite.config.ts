// The web app's build (docs/design/web.md §2). Its dist/ is copied into the `api` image, which
// serves it (ADR-0010): hashed files under assets/, index.html at the root.
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // `@/…` is what shadcn/ui's components import by, and what this app uses for its own modules.
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false },
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"], globals: false },
});
