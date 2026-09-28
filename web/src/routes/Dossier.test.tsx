// Building a dossier (T044; docs/design/web/dossier.svg, docs/design/api.md §6).
// [REQ-013] [NFR-009]
//
// The API is stubbed at `fetch`, so the whole screen runs: choosing records, the warning about
// located photos, the request, the wait, and the ready dossier's download.
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentView, DossierView } from "../api/types";
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

const RECORDED = {
  captured_at: "2026-09-01T10:14:00+02:00",
  device: "Samsung SM-A536B",
  latitude: -25.742,
  longitude: 28.188,
};
const UNRECORDED = {
  captured_at: "not recorded",
  device: "not recorded",
  latitude: "not recorded",
  longitude: "not recorded",
} as const;

function a(document: Partial<DocumentView> & { id: string }): DocumentView {
  return {
    kind: "photo",
    status: "processed",
    content_type: "image/jpeg",
    size_bytes: 2048,
    sha256: "ab".repeat(32),
    stored_at: "2026-09-01T08:16:00Z",
    failure_reason: null,
    ...document,
  };
}

const LEASE = a({
  id: "11111111-1111-4111-8111-111111111111",
  kind: "lease",
  content_type: "application/pdf",
  stored_at: "2026-08-30T07:30:00Z",
});
const WALL = a({
  id: "22222222-2222-4222-8222-222222222222",
  stored_at: "2026-09-01T08:16:00Z",
  capture: RECORDED,
});
const BATHROOM = a({
  id: "33333333-3333-4333-8333-333333333333",
  stored_at: "2026-09-01T08:17:00Z",
  capture: RECORDED,
});
const HALLWAY = a({
  id: "44444444-4444-4444-8444-444444444444",
  stored_at: "2026-09-01T08:18:00Z",
  capture: UNRECORDED,
});
const READING = a({
  id: "55555555-5555-4555-8555-555555555555",
  kind: "lease",
  status: "stored",
  stored_at: "2026-09-02T08:00:00Z",
});

const DOSSIER_ID = "99999999-9999-4999-8999-999999999999";
const REQUESTED: DossierView = {
  id: DOSSIER_ID,
  status: "compiling",
  requested_at: "2026-10-01T09:00:00Z",
  page_count: null,
  size_bytes: null,
  sha256: null,
  failure_reason: null,
  download_url: null,
  expires_at: null,
};
const READY: DossierView = {
  ...REQUESTED,
  status: "ready",
  page_count: 38,
  size_bytes: 9_646_899,
  sha256: "51c2" + "0".repeat(56) + "a9e4",
  download_url:
    "https://tokelo-staging-documents.s3.eu-west-1.amazonaws.com/d.pdf?x=1",
  expires_at: "2099-01-01T00:00:00Z",
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
  fetch.mockImplementation(async () => responses[responses.length - 1].clone());
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function listed(...documents: DocumentView[]): Response {
  return json({ documents });
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("[REQ-013] choosing the records", () => {
  it("offers every finished record, and none still being read", async () => {
    answers(listed(LEASE, WALL, READING));
    renderRoute("/dossier", { auth });

    expect(
      await screen.findByRole("checkbox", {
        name: "Lease · stored 2026-08-30 09:30 SAST",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("checkbox", {
        name: "Photo · stored 2026-09-01 10:16 SAST",
      }),
    ).toBeTruthy();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("says how many chosen photos show where they were taken, before building", async () => {
    answers(listed(WALL, BATHROOM, HALLWAY));
    renderRoute("/dossier", { auth });

    const boxes = await screen.findAllByRole("checkbox");
    expect(screen.queryByText(/include their location/)).toBeNull();

    await userEvent.click(boxes[0]);
    expect(
      screen.getByText("1 selected photo includes its location"),
    ).toBeTruthy();
    await userEvent.click(boxes[1]);
    await userEvent.click(boxes[2]); // the hallway: no location recorded
    expect(
      screen.getByText("2 selected photos include their location"),
    ).toBeTruthy();
  });

  it("shows the API's own reason when nothing is chosen", async () => {
    answers(
      listed(WALL),
      json(
        {
          error: {
            code: "refused",
            message:
              "Nothing is selected: choose at least one document to put in the dossier.",
          },
        },
        422,
      ),
    );
    renderRoute("/dossier", { auth });

    await userEvent.click(
      await screen.findByRole("button", { name: "Build dossier" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nothing is selected: choose at least one document",
    );
  });

  it("says where to start when there is nothing finished to choose", async () => {
    answers(listed(READING));
    renderRoute("/dossier", { auth });

    expect(
      await screen.findByText("Nothing to put in a dossier yet"),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Build dossier" })).toBeNull();
  });
});

describe("[REQ-013] building and downloading", () => {
  it("asks for the chosen records, waits, and offers the ready dossier", async () => {
    const fetch = answers(
      listed(LEASE, WALL),
      json({ dossier_id: DOSSIER_ID }, 202),
      json(REQUESTED),
      json(READY),
    );
    renderRoute("/dossier", { auth });

    await userEvent.click(
      await screen.findByRole("checkbox", { name: /Lease/ }),
    );
    await userEvent.click(screen.getByRole("checkbox", { name: /Photo/ }));
    await userEvent.click(
      screen.getByRole("button", { name: "Build dossier" }),
    );

    expect(await screen.findByText("Building your dossier")).toBeTruthy();
    expect(await screen.findByText("Ready")).toBeTruthy();
    expect(screen.getByText("Dispute dossier, 38 pages, 9.2 MB")).toBeTruthy();
    expect(screen.getByText("SHA-256: 51c2…a9e4")).toBeTruthy();
    const download = screen.getByRole("link", {
      name: "Download (link valid for 5 minutes)",
    });
    expect(download.getAttribute("href")).toBe(READY.download_url);

    const [path, init] = fetch.mock.calls[1];
    expect(path).toBe("/api/dossiers");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      document_ids: [LEASE.id, WALL.id],
    });
    expect(fetch.mock.calls[2][0]).toBe(`/api/dossiers/${DOSSIER_ID}`);
  });

  it("says why a dossier failed", async () => {
    answers(
      listed(WALL),
      json({ dossier_id: DOSSIER_ID }, 202),
      json({
        ...REQUESTED,
        status: "failed",
        failure_reason:
          "Too many records for one dossier: it would pass 100 MB. Choose fewer records and build it again.",
      }),
    );
    renderRoute("/dossier", { auth });

    await userEvent.click(await screen.findByRole("checkbox"));
    await userEvent.click(
      screen.getByRole("button", { name: "Build dossier" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many records for one dossier",
    );
  });
});

describe("[REQ-013] a download link that has run out", () => {
  const EXPIRED: DossierView = { ...READY, expires_at: "2020-01-01T00:00:00Z" };
  const FRESH_URL =
    "https://tokelo-staging-documents.s3.eu-west-1.amazonaws.com/d.pdf?fresh=1";

  it("fetches a fresh link and goes to it, rather than following the dead one", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const fetch = answers(
      listed(WALL),
      json({ dossier_id: DOSSIER_ID }, 202),
      json(EXPIRED),
      json({ ...READY, download_url: FRESH_URL }),
    );
    renderRoute("/dossier", { auth });

    await userEvent.click(await screen.findByRole("checkbox"));
    await userEvent.click(
      screen.getByRole("button", { name: "Build dossier" }),
    );
    await userEvent.click(
      await screen.findByRole("link", {
        name: "Download (link valid for 5 minutes)",
      }),
    );

    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith(FRESH_URL));
    expect(fetch.mock.calls[3][0]).toBe(`/api/dossiers/${DOSSIER_ID}`);
  });

  it("says so when a fresh link can't be had", async () => {
    vi.stubGlobal("location", { ...window.location, assign: vi.fn() });
    answers(
      listed(WALL),
      json({ dossier_id: DOSSIER_ID }, 202),
      json(EXPIRED),
      json({ error: { code: "not_found", message: "No such dossier." } }, 404),
    );
    renderRoute("/dossier", { auth });

    await userEvent.click(await screen.findByRole("checkbox"));
    await userEvent.click(
      screen.getByRole("button", { name: "Build dossier" }),
    );
    await userEvent.click(
      await screen.findByRole("link", {
        name: "Download (link valid for 5 minutes)",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No such dossier.",
    );
  });
});

describe("[NFR-009] accessibility", () => {
  it("has no axe violations with records chosen and the warning shown", async () => {
    answers(listed(LEASE, WALL, HALLWAY));
    const { container } = renderRoute("/dossier", { auth });

    await userEvent.click(
      await screen.findByRole("checkbox", { name: /10:16/ }),
    );
    await screen.findByText(/includes its location/);
    await axeClean(container);
  });

  it("has no axe violations with a dossier ready", async () => {
    answers(listed(WALL), json({ dossier_id: DOSSIER_ID }, 202), json(READY));
    const { container } = renderRoute("/dossier", { auth });

    await userEvent.click(await screen.findByRole("checkbox"));
    await userEvent.click(
      screen.getByRole("button", { name: "Build dossier" }),
    );
    await screen.findByText("Ready");
    await axeClean(container);
  });
});
