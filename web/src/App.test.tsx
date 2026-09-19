import { cleanup, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";

afterEach(cleanup);

describe("the app shell", () => {
  it("names the app", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Tokelo" })).toBeTruthy();
  });

  it("says that it gives legal information, not legal advice", () => {
    render(<App />);
    expect(screen.getByText("Legal information, not legal advice.")).toBeTruthy();
  });

  it("has no accessibility violations (axe, WCAG 2.1 AA; NFR-009)", async () => {
    const { container } = render(<App />);
    const results = await axe.run(container, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] });
    expect(results.violations).toEqual([]);
  });
});
