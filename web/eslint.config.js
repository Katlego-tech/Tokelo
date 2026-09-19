// The web app's lint (docs/design/web.md). The one rule of its own: no injected HTML, because
// React escapes text and the content security policy is 'self' (web.md, Threats).
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist/"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Never inject HTML: React escapes text, and the CSP is 'self' (docs/design/web.md).",
        },
      ],
    },
  },
);
