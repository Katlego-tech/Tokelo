// Uploading (T027; docs/design/web/upload.svg, docs/design/api.md §4).
// [REQ-002] [REQ-003] [NFR-009]
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const TICKET = {
  document_id: "33333333-3333-4333-8333-333333333333",
  url: "https://tokelo-staging-documents.s3.eu-west-1.amazonaws.com/",
  fields: {
    key: "uploads/t/lease/33333333-3333-4333-8333-333333333333",
    policy: "p",
  },
  expires_at: "2026-09-21T06:15:00Z",
};

/** An XMLHttpRequest that records what was sent and reports success, since jsdom has no S3. */
function recordingXhr(sent: { form?: FormData; url?: string }) {
  return class {
    upload = {
      addEventListener: (_: string, listener: (e: ProgressEvent) => void) =>
        void listener,
    };
    status = 204;
    private listeners: Record<string, () => void> = {};
    open(_method: string, url: string) {
      sent.url = url;
    }
    addEventListener(name: string, listener: () => void) {
      this.listeners[name] = listener;
    }
    send(form: FormData) {
      sent.form = form;
      this.listeners.load?.();
    }
  } as unknown as typeof XMLHttpRequest;
}

let sent: { form?: FormData; url?: string };

beforeEach(() => {
  vi.clearAllMocks();
  sent = {};
  vi.stubGlobal("XMLHttpRequest", recordingXhr(sent));
});

afterEach(() => vi.unstubAllGlobals());

function answers(...responses: Response[]) {
  const fetch = vi.fn();
  for (const response of responses) fetch.mockResolvedValueOnce(response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function json(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

async function chooseMany(name: RegExp, files: File[]) {
  const input = screen.getByLabelText(name) as HTMLInputElement;
  await userEvent.setup().upload(input, files);
}

async function choose(name: RegExp, file: File, { asPickerWould = true } = {}) {
  const input = screen.getByLabelText(name) as HTMLInputElement;
  if (asPickerWould) {
    await userEvent.setup().upload(input, file);
    return;
  }
  // `accept` is a hint to the file picker, not a rule — phones and desktops both hand over files
  // it doesn't cover, which is why the guard exists. user-event filters by accept whatever it is
  // told, so that case is put on the input directly.
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

const PDF = () =>
  new File([new Uint8Array([37, 80, 68, 70])], "lease.pdf", {
    type: "application/pdf",
  });

describe("[REQ-002] the file goes straight to storage", () => {
  it("asks the API for a ticket, then posts the file to S3 with the fields it was given", async () => {
    const fetch = answers(
      json(TICKET, 201),
      json({ id: TICKET.document_id, status: "stored" }),
    );
    renderRoute("/lease/new", { auth });

    await choose(/choose a pdf/i, PDF());

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const [path, options] = fetch.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/uploads");
    expect(options.method).toBe("POST");
    expect(JSON.parse(String(options.body))).toMatchObject({
      kind: "lease",
      content_type: "application/pdf",
      filename: "lease.pdf",
    });
    expect((options.headers as Record<string, string>).authorization).toBe(
      "Bearer a-token",
    );

    // The bytes went to S3, with the signed fields, and never to the API.
    await waitFor(() => expect(sent.url).toBe(TICKET.url));
    expect(sent.form?.get("key")).toBe(TICKET.fields.key);
    expect(sent.form?.get("file")).toBeInstanceOf(File);
    expect(
      fetch.mock.calls.every(([called]) => !String(called).includes("s3")),
    ).toBe(true);
  });

  it("tells the tenant it is processing once the file is in", async () => {
    answers(
      json(TICKET, 201),
      json({ id: TICKET.document_id, status: "stored" }),
    );
    renderRoute("/lease/new", { auth });

    await choose(/choose a pdf/i, PDF());

    expect(
      await screen.findByRole("status", { name: /processing/i }),
    ).toHaveTextContent(/you can leave this page/i);
  });
});

describe("[REQ-003] what a tenant is told before spending their data", () => {
  it("refuses a Word document by name, without asking the API", async () => {
    const fetch = answers();
    renderRoute("/lease/new", { auth });

    await choose(
      /choose a pdf/i,
      new File(["x"], "lease.doc", { type: "application/msword" }),
      {
        asPickerWould: false,
      },
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /word documents aren't accepted/i,
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("refuses a file over the limit, saying how big it is", async () => {
    const fetch = answers();
    renderRoute("/lease/new", { auth });

    const big = new File(["x"], "lease.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 21 * 1024 * 1024 });
    await choose(/choose a pdf/i, big);

    expect(await screen.findByRole("alert")).toHaveTextContent(/21\.0 MB/);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows the server's own reason when the server refuses", async () => {
    answers(
      json(
        {
          error: { code: "refused", message: "A lease may be at most 20 MB." },
        },
        422,
      ),
    );
    renderRoute("/lease/new", { auth });

    await choose(/choose a pdf/i, PDF());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /at most 20 MB/i,
    );
  });
});

describe("[NFR-009] accessibility", () => {
  it("has no axe violations on the lease upload screen", async () => {
    const { container } = renderRoute("/lease/new", { auth });
    await axeClean(container);
  });

  it("has no axe violations on the evidence screen", async () => {
    const { container } = renderRoute("/evidence/new", { auth });
    await axeClean(container);
  });
});

describe("[REQ-003] photos become one lease, and the tenant sees them first", () => {
  const photo = (name: string) => new File([name], name, { type: "image/jpeg" });

  it("shows every page chosen, in order, before anything is sent", async () => {
    const fetch = answers();
    renderRoute("/lease/new", { auth });

    await chooseMany(/take or choose photos/i, [photo("p1.jpg"), photo("p2.jpg"), photo("p3.jpg")]);

    const pages = await screen.findAllByRole("img");
    expect(pages.map((p) => p.getAttribute("alt"))).toEqual(["Page 1", "Page 2", "Page 3"]);
    // Nothing has left the phone yet: a tenant checks the pages first.
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /upload 3 pages/i })).toBeEnabled();
  });

  it("lets a page that came out blurred be taken out again", async () => {
    answers();
    renderRoute("/lease/new", { auth });

    await chooseMany(/take or choose photos/i, [photo("p1.jpg"), photo("p2.jpg")]);
    await userEvent.setup().click(screen.getByRole("button", { name: /remove page 1/i }));

    const pages = await screen.findAllByRole("img");
    expect(pages).toHaveLength(1);
    expect(screen.getByRole("button", { name: /upload 1 page$/i })).toBeInTheDocument();
  });

  it("refuses more pages than a lease may have, before joining any of them", async () => {
    answers();
    renderRoute("/lease/new", { auth });

    await chooseMany(
      /take or choose photos/i,
      Array.from({ length: 31 }, (_, n) => photo(`p${n}.jpg`)),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/at most 30 pages/i);
  });
});
