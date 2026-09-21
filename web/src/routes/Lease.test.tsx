// A lease's flags on the screen (T035; docs/design/web/lease.svg, docs/design/api.md §6).
// [REQ-004] [REQ-005] [REQ-006] [REQ-007] [NFR-009]
//
// The API is stubbed at `fetch`, so what is exercised here is the whole screen: the wait while
// the lease is still being read, the wording a clause with nothing against it gets, and the
// pages the reader couldn't manage.
import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Auth } from "../auth/AuthContext";
import type { LeaseFlags } from "../api/types";
import { axeClean } from "../test/axe";
import { renderRoute } from "../test/render";

const ID = "33333333-3333-4333-8333-333333333333";

const auth: Auth = {
  status: "signed-in",
  email: "tenant@example.com",
  signUp: vi.fn(async () => {}),
  confirm: vi.fn(async () => {}),
  signIn: vi.fn(async () => {}),
  signOut: vi.fn(async () => {}),
  token: vi.fn(async () => "a-token"),
};

const LEASE: LeaseFlags = {
  status: "analysed",
  page_count: 4,
  unreadable_pages: [],
  notice: "This is legal information, not legal advice.",
  clauses: [
    {
      label: "7.2",
      first_page: 2,
      text: "The landlord may evict the tenant without recourse to a court of law.",
      flags: [
        {
          rule_id: "eviction-without-court-order",
          explanation:
            "A landlord may only evict a tenant under an order of court.",
          sections: [
            {
              id: "PIE-4",
              act: "Prevention of Illegal Eviction from and Unlawful Occupation of Land Act 19 of 1998",
              section: "4",
              title: "Eviction of unlawful occupiers",
            },
          ],
        },
      ],
    },
    {
      label: "8.2",
      first_page: 3,
      text: "The tenant shall keep the garden in a neat and tidy condition.",
      flags: [],
      finding: "no issue found by these checks",
    },
  ],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function answers(...responses: Response[]) {
  const fetch = vi.fn();
  for (const response of responses) fetch.mockResolvedValueOnce(response);
  fetch.mockResolvedValue(responses[responses.length - 1]);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function stillReading(): Response {
  return json(
    {
      error: {
        code: "still_reading",
        message: "This lease is still being read.",
      },
    },
    409,
  );
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("[REQ-005] a lease's clauses", () => {
  it("shows every clause with its number, its page and the lease's own words", async () => {
    answers(json(LEASE));
    renderRoute(`/lease/${ID}`, { auth });

    expect(await screen.findByText("Clause 7.2")).toBeTruthy();
    expect(screen.getByText("Clause 8.2")).toBeTruthy();
    expect(screen.getByText(/without recourse to a court of law/)).toBeTruthy();
    expect(screen.getByText("Page 2")).toBeTruthy();
  });

  it("states how long the lease is, beside whether it was analysed", async () => {
    answers(json(LEASE));
    renderRoute(`/lease/${ID}`, { auth });

    expect(await screen.findByText("Analysed")).toBeTruthy();
    expect(screen.getByText("4 pages")).toBeTruthy();
  });
});

describe("[REQ-006] what a flag rests on", () => {
  it("shows the explanation and the section a tenant can look up", async () => {
    answers(json(LEASE));
    renderRoute(`/lease/${ID}`, { auth });

    expect(
      await screen.findByText(/only evict a tenant under an order of court/),
    ).toBeTruthy();
    expect(
      screen.getByText(/Section 4 · Eviction of unlawful occupiers/),
    ).toBeTruthy();
    expect(screen.getByText(/Act 19 of 1998/)).toBeTruthy();
  });

  it("carries the legal-information notice the API sent, word for word", async () => {
    answers(json(LEASE));
    renderRoute(`/lease/${ID}`, { auth });

    expect(await screen.findByText(LEASE.notice)).toBeTruthy();
  });
});

describe("[REQ-007] a clause nothing matched", () => {
  it("says what was checked and never that the clause is lawful", async () => {
    answers(json(LEASE));
    renderRoute(`/lease/${ID}`, { auth });

    expect(
      await screen.findByText("No issue found by these checks"),
    ).toBeTruthy();
    // The notice is taken out first: "This is legal information, not legal advice" is the one
    // place those words belong, and it is asserted above. What is swept is everything else.
    const said = (document.body.textContent ?? "").replace(LEASE.notice, "");
    expect(
      /\b(is|are|seems?|looks?) (lawful|legal|fine|valid|ok)\b/i.test(said),
    ).toBe(false);
  });
});

describe("[REQ-004] the pages nobody could read", () => {
  it("names them by number, before any flag, and says nothing was guessed", async () => {
    answers(json({ ...LEASE, unreadable_pages: [3] }));
    renderRoute(`/lease/${ID}`, { auth });

    expect(await screen.findByText("Page 3 couldn't be read")).toBeTruthy();
    expect(screen.getByText(/was\s+guessed at/)).toBeTruthy();
  });

  it("reads as a list when more than one page failed", async () => {
    answers(json({ ...LEASE, unreadable_pages: [2, 3, 5] }));
    renderRoute(`/lease/${ID}`, { auth });

    expect(
      await screen.findByText("Pages 2, 3 and 5 couldn't be read"),
    ).toBeTruthy();
  });
});

describe("while the lease is still being read", () => {
  it("waits rather than showing half of it, then shows it when it is done", async () => {
    answers(stillReading(), stillReading(), json(LEASE));
    renderRoute(`/lease/${ID}`, { auth });

    expect(await screen.findByText("Reading your lease")).toBeTruthy();
    expect(await screen.findByText("Clause 7.2")).toBeTruthy();
    expect(screen.queryByText("Reading your lease")).toBeNull();
  });

  it("says a lease that failed to be read failed, rather than showing no flags", async () => {
    answers(
      json({
        ...LEASE,
        status: "failed",
        clauses: [],
        unreadable_pages: [1, 2],
      }),
    );
    renderRoute(`/lease/${ID}`, { auth });

    expect(await screen.findByText("Failed")).toBeTruthy();
    expect(screen.getByText("We could not read this file.")).toBeTruthy();
  });
});

describe("[REQ-001] a lease that isn't the tenant's", () => {
  it("is not found, and offers the only thing that would help", async () => {
    answers(
      json({ error: { code: "not_found", message: "No such lease." } }, 404),
    );
    renderRoute(`/lease/${ID}`, { auth });

    expect(await screen.findByText("No such lease")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Upload one" })).toBeTruthy();
  });
});

describe("[NFR-009] accessibility", () => {
  it("has no axe violations with flags on the screen", async () => {
    answers(json({ ...LEASE, unreadable_pages: [3] }));
    const { container } = renderRoute(`/lease/${ID}`, { auth });

    await screen.findByText("Clause 7.2");
    await axeClean(container);
  });

  it("has no axe violations while it is still reading", async () => {
    answers(stillReading());
    const { container } = renderRoute(`/lease/${ID}`, { auth });

    await screen.findByText("Reading your lease");
    await waitFor(() => expect(container.querySelector("h1")).toBeTruthy());
    await axeClean(container);
  });
});
