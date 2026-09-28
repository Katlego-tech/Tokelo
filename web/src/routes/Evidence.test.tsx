// A tenant's evidence (T040; docs/design/web/evidence.svg, docs/design/api.md §6).
// [REQ-008] [REQ-009] [REQ-010] [NFR-009]
//
// The API is stubbed at `fetch`, so the whole screen runs: the list, what each photograph says
// about itself (or that it says nothing), and a verification with either answer.
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentView, Verification } from "../api/types";
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

const WALL_DIGEST =
  "3f9a0000000000000000000000000000000000000000000000000000000c21e";
const BATH_DIGEST =
  "8b01000000000000000000000000000000000000000000000000000000077d0";

function a(document: Partial<DocumentView> & { id: string }): DocumentView {
  return {
    kind: "photo",
    status: "processed",
    content_type: "image/jpeg",
    size_bytes: 2048,
    sha256: null,
    stored_at: null,
    failure_reason: null,
    ...document,
  };
}

const WALL = a({
  id: "11111111-1111-4111-8111-111111111111",
  sha256: WALL_DIGEST,
  stored_at: "2026-09-01T08:16:00Z",
  capture: {
    captured_at: "2026-09-01T10:14:00+02:00",
    device: "Samsung SM-A536B",
    latitude: -25.742,
    longitude: 28.188,
  },
});
const BATHROOM = a({
  id: "22222222-2222-4222-8222-222222222222",
  sha256: BATH_DIGEST,
  stored_at: "2026-09-01T08:17:00Z",
  capture: {
    captured_at: "not recorded",
    device: "not recorded",
    latitude: "not recorded",
    longitude: "not recorded",
  },
});
const NOTICE = a({
  id: "33333333-3333-4333-8333-333333333333",
  kind: "notice",
  content_type: "application/pdf",
  sha256: "c0ffee" + "0".repeat(58),
  stored_at: "2026-09-03T07:30:00Z",
});
const LEASE = a({
  id: "44444444-4444-4444-8444-444444444444",
  kind: "lease",
  content_type: "application/pdf",
  sha256: "1ea5e" + "0".repeat(59),
  stored_at: "2026-08-30T07:30:00Z",
});

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

function listed(...documents: DocumentView[]): Response {
  return json({ documents });
}

function card(title: RegExp): HTMLElement {
  return screen.getByRole("article", { name: title });
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("[REQ-009] what each photograph says about itself", () => {
  it("shows its capture time in SAST, its phone, and that its location is recorded", async () => {
    answers(listed(WALL));
    renderRoute("/evidence", { auth });

    const wall = await screen.findByRole("article", { name: /Photo/ });
    expect(
      within(wall).getByText("Captured: 2026-09-01 10:14 SAST"),
    ).toBeTruthy();
    expect(within(wall).getByText("Device: Samsung SM-A536B")).toBeTruthy();
    expect(within(wall).getByText("Location: recorded")).toBeTruthy();
  });

  it("never shows where the photo was taken, only that it's known", async () => {
    answers(listed(WALL));
    renderRoute("/evidence", { auth });

    await screen.findByText("Location: recorded");
    expect(document.body.textContent).not.toMatch(/25\.742|28\.188/);
  });

  it("says 'not recorded' for what a photo doesn't carry, and invents nothing", async () => {
    answers(listed(BATHROOM));
    renderRoute("/evidence", { auth });

    await screen.findByText("Captured: not recorded");
    expect(screen.getByText("Device: not recorded")).toBeTruthy();
    expect(screen.getByText("Location: not recorded")).toBeTruthy();
  });
});

describe("[REQ-008] each file's fingerprint", () => {
  it("names each file by its kind and when it was stored, with its digest", async () => {
    answers(listed(WALL, NOTICE));
    renderRoute("/evidence", { auth });

    const notice = await screen.findByRole("article", {
      name: "Notice · stored 2026-09-03 09:30 SAST",
    });
    expect(within(notice).getByText("SHA-256: c0ff…0000")).toBeTruthy();
    expect(card(/Photo · stored 2026-09-01 10:16 SAST/).textContent).toContain(
      "SHA-256: 3f9a…c21e",
    );
  });

  it("lists evidence only, newest first; a lease is not evidence", async () => {
    answers(listed(LEASE, WALL, NOTICE, BATHROOM));
    renderRoute("/evidence", { auth });

    await screen.findByText(/Notice · stored/);
    const titles = screen
      .getAllByRole("article")
      .map((article) => article.getAttribute("aria-label"));
    expect(titles).toEqual([
      "Notice · stored 2026-09-03 09:30 SAST",
      "Photo · stored 2026-09-01 10:17 SAST",
      "Photo · stored 2026-09-01 10:16 SAST",
    ]);
  });

  it("says what is still happening to a file, and why one failed", async () => {
    answers(
      listed(
        a({ id: "a1111111-1111-4111-8111-111111111111", status: "requested" }),
        a({
          id: "a2222222-2222-4222-8222-222222222222",
          kind: "chat",
          status: "failed",
          sha256: "d" + "0".repeat(63),
          stored_at: "2026-09-04T07:00:00Z",
          failure_reason:
            "This isn't a WhatsApp export: no line is in either of WhatsApp's formats.",
        }),
        a({ id: "a3333333-3333-4333-8333-333333333333", status: "expired" }),
      ),
    );
    renderRoute("/evidence", { auth });

    expect(
      await screen.findByText(/This isn't a WhatsApp export/),
    ).toBeTruthy();
    expect(screen.getByText("Waiting for the file to arrive")).toBeTruthy();
    // An upload that never happened isn't evidence of anything, and isn't listed.
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("has somewhere to start when there is nothing yet", async () => {
    answers(listed(LEASE));
    renderRoute("/evidence", { auth });

    expect(await screen.findByText("No evidence yet")).toBeTruthy();
    const add = screen.getByRole("link", {
      name: "Add photos, notices or chats",
    });
    expect(add.getAttribute("href")).toBe("/evidence/new");
  });
});

describe("[REQ-010] verifying a file", () => {
  it("asks the API to hash the stored file again, and says when it's unchanged", async () => {
    const verification: Verification = {
      matches: true,
      recorded_sha256: WALL_DIGEST,
      computed_sha256: WALL_DIGEST,
      verified_at: "2026-09-27T12:00:00Z",
    };
    const fetch = answers(listed(WALL), json(verification));
    renderRoute("/evidence", { auth });

    const wall = await screen.findByRole("article", { name: /Photo/ });
    await userEvent.click(
      within(wall).getByRole("button", { name: "Verify this file" }),
    );

    expect(
      await within(wall).findByText("Unchanged: matches its stored digest"),
    ).toBeTruthy();
    expect(
      within(wall).getByText(/Checked 2026-09-27 14:00 SAST/),
    ).toBeTruthy();
    const [path, init] = fetch.mock.calls[1];
    expect(path).toBe(`/api/evidence/${WALL.id}/verify`);
    expect(init.method).toBe("POST");
  });

  it("says plainly when a file has changed, and shows both digests", async () => {
    const edited = "e" + "0".repeat(63);
    answers(
      listed(WALL),
      json({
        matches: false,
        recorded_sha256: WALL_DIGEST,
        computed_sha256: edited,
        verified_at: "2026-09-27T12:00:00Z",
      }),
    );
    renderRoute("/evidence", { auth });

    const wall = await screen.findByRole("article", { name: /Photo/ });
    await userEvent.click(
      within(wall).getByRole("button", { name: "Verify this file" }),
    );

    const changed = await within(wall).findByRole("alert");
    expect(changed.textContent).toContain(
      "Changed: doesn't match its stored digest",
    );
    expect(changed.textContent).toContain(WALL_DIGEST);
    expect(changed.textContent).toContain(edited);
  });

  it("shows the API's own reason when a file can't be verified yet", async () => {
    answers(
      listed(WALL),
      json(
        {
          error: {
            code: "not_stored",
            message: "This file hasn't been stored and fingerprinted yet.",
          },
        },
        409,
      ),
    );
    renderRoute("/evidence", { auth });

    const wall = await screen.findByRole("article", { name: /Photo/ });
    await userEvent.click(
      within(wall).getByRole("button", { name: "Verify this file" }),
    );

    expect(
      await within(wall).findByText(
        "This file hasn't been stored and fingerprinted yet.",
      ),
    ).toBeTruthy();
  });

  it("offers no verification for a file that has no digest yet", async () => {
    answers(
      listed(
        a({ id: "a1111111-1111-4111-8111-111111111111", status: "requested" }),
      ),
    );
    renderRoute("/evidence", { auth });

    await screen.findByText("Waiting for the file to arrive");
    expect(
      screen.queryByRole("button", { name: "Verify this file" }),
    ).toBeNull();
  });
});

describe("[NFR-009] accessibility", () => {
  it("has no axe violations with evidence listed and a file verified", async () => {
    answers(
      listed(WALL, BATHROOM, NOTICE),
      json({
        matches: false,
        recorded_sha256: WALL_DIGEST,
        computed_sha256: "e" + "0".repeat(63),
        verified_at: "2026-09-27T12:00:00Z",
      }),
    );
    const { container } = renderRoute("/evidence", { auth });

    const wall = await screen.findByRole("article", { name: /10:16/ });
    await userEvent.click(
      within(wall).getByRole("button", { name: "Verify this file" }),
    );
    await within(wall).findByRole("alert");
    await axeClean(container);
  });

  it("has no axe violations when there is nothing yet", async () => {
    answers(listed());
    const { container } = renderRoute("/evidence", { auth });

    await screen.findByText("No evidence yet");
    await axeClean(container);
  });
});
