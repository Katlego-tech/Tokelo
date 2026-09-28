// Asking a rights question (T047; docs/design/web/navigator.svg, docs/design/api.md §6).
// [REQ-014] [REQ-006] [NFR-009]
//
// The API is stubbed at `fetch`, so the whole screen runs: a question, the written answer with
// the sections it rests on and the notice, or the plain "outside" reply.
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Answer, Outside } from "../api/types";
import type { Auth } from "../auth/AuthContext";
import { axeClean } from "../test/axe";
import { renderRoute } from "../test/render";

const auth: Auth = {
  status: "signed-in",
  email: "tenant@example.com",
  signUp: vi.fn(async () => {}),
  confirm: vi.fn(async () => {}),
  signIn: vi.fn(async () => {}),
  signOut: vi.fn(async () => {}),
  token: vi.fn(async () => "a-token"),
};

const ANSWER: Answer = {
  topic: "Services and lock-outs",
  answer:
    "A landlord may not cause the supply to be cut without a court order (regulation 13(1)).\n\n" +
    "Neither side may change the locks:\n" +
    "- without reasonable notice\n" +
    "- without giving the other duplicate keys at once",
  sections: [
    {
      id: "GT-REG-13",
      act: "Unfair Practices Regulations, 2001 (Gauteng)",
      section: "13",
      title: "Municipal Services",
    },
    {
      id: "PIE-8",
      act: "Prevention of Illegal Eviction from and Unlawful Occupation of Land Act 19 of 1998",
      section: "8",
      title: "Offences and private prosecutions",
    },
  ],
  notice: "This is legal information, not legal advice.",
};

const OUTSIDE: Outside = {
  outside: true,
  message:
    "Tokelo has no written answer for this question, so it won't guess at one. The Rental Housing Tribunal hears complaints from tenants and landlords about unfair practices.",
  refer_to: "the Rental Housing Tribunal",
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
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function ask(question: string) {
  await userEvent.type(screen.getByLabelText("Your question"), question);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("[REQ-014] a curated topic", () => {
  it("sends the question and shows the topic's written answer", async () => {
    const fetch = answers(json(ANSWER));
    renderRoute("/ask", { auth });

    await ask("Can my landlord cut off my water?");

    expect(
      await screen.findByRole("heading", { name: "Services and lock-outs" }),
    ).toBeTruthy();
    expect(screen.getByText(/may not cause the supply to be cut/)).toBeTruthy();
    expect(
      screen.getByText("without giving the other duplicate keys at once"),
    ).toBeTruthy();
    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe("/api/navigator");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      question: "Can my landlord cut off my water?",
    });
  });

  it("[REQ-006] shows every section the answer rests on, to look up", async () => {
    answers(json(ANSWER));
    renderRoute("/ask", { auth });

    await ask("Can my landlord cut off my water?");

    expect(
      await screen.findByText("Section 13 · Municipal Services"),
    ).toBeTruthy();
    expect(
      screen.getByText("Unfair Practices Regulations, 2001 (Gauteng)"),
    ).toBeTruthy();
    expect(
      screen.getByText("Section 8 · Offences and private prosecutions"),
    ).toBeTruthy();
  });

  it("carries the legal-information notice the API sent, word for word", async () => {
    answers(json(ANSWER));
    renderRoute("/ask", { auth });

    await ask("Can my landlord cut off my water?");

    expect(await screen.findByText(ANSWER.notice)).toBeTruthy();
  });
});

describe("[REQ-014] a question no topic covers", () => {
  it("says so plainly, in the API's own words, and names the Tribunal", async () => {
    answers(json(OUTSIDE));
    renderRoute("/ask", { auth });

    await ask("Can I sublet my flat on Airbnb?");

    expect(
      await screen.findByRole("heading", {
        name: "Outside what Tokelo covers",
      }),
    ).toBeTruthy();
    expect(screen.getByText(OUTSIDE.message)).toBeTruthy();
    expect(screen.queryByText(/Section \d/)).toBeNull();
  });
});

describe("a question the API refuses", () => {
  it("shows the API's reason", async () => {
    answers(
      json(
        {
          error: {
            code: "refused",
            message: "Ask a question of 3 to 500 characters.",
          },
        },
        422,
      ),
    );
    renderRoute("/ask", { auth });

    await ask("hi");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ask a question of 3 to 500 characters.",
    );
  });
});

describe("[NFR-009] accessibility", () => {
  it("has no axe violations with an answer shown", async () => {
    answers(json(ANSWER));
    const { container } = renderRoute("/ask", { auth });

    await ask("Can my landlord cut off my water?");
    await screen.findByRole("heading", { name: "Services and lock-outs" });
    await axeClean(container);
  });

  it("has no axe violations with the outside reply shown", async () => {
    answers(json(OUTSIDE));
    const { container } = renderRoute("/ask", { auth });

    await ask("Can I sublet my flat on Airbnb?");
    await screen.findByRole("heading", { name: "Outside what Tokelo covers" });
    await axeClean(container);
  });
});
