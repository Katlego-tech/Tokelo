// axe on every screen (NFR-009, WCAG 2.1 AA; docs/design/web.md §9). pa11y in the release can
// only reach the pages a signed-out visitor sees, so the signed-in ones are checked here.
import axe from "axe-core";
import { expect } from "vitest";

export async function axeClean(container: HTMLElement): Promise<void> {
  const results = await axe.run(container, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    },
  });
  const found = results.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.length})`,
  );
  expect(found, found.join("\n")).toEqual([]);
}
