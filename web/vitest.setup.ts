// jest-dom's matchers (toBeDisabled, toHaveTextContent…), so a test reads as what a tenant sees.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// The tests import what they use rather than relying on globals, so React Testing Library's own
// clean-up has to be asked for: without it every screen stays in the document and the next test
// finds two of everything.
afterEach(cleanup);

// jsdom has no ResizeObserver, and Radix's primitives measure themselves. A browser has one;
// this is the smallest thing that lets the same components run under the tests.
class NoResizeObserver implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= NoResizeObserver;
