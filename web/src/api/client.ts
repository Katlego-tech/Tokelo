// One way in and out of the API (docs/design/web.md §4, §7).
//
// Two things live here so that no screen has to remember them:
//
// 1. **The token.** Every /api/ call carries the tenant's access token; a screen never handles
//    one. A call made without a signed-in tenant is a bug, and fails here rather than quietly
//    asking the API for somebody else's records.
// 2. **Waking up.** A cold function can answer 503 with Retry-After (api.md §4). The client
//    waits and tries again, up to four times, and tells the app it is waiting so the banner can
//    say so (NFR-002). A screen that had to do this itself would do it four different ways.

import type { ApiError, Config, DocumentView, UploadTicket } from "./types";

export const RETRIES = 4;

export type Waking = (waiting: boolean) => void;

export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function loadConfig(): Promise<Config> {
  const answer = await fetch("/config.json", {
    headers: { accept: "application/json" },
  });
  if (!answer.ok)
    throw new ApiFailure(
      answer.status,
      "no_config",
      "This app isn't configured.",
    );
  return (await answer.json()) as Config;
}

type Call = {
  path: string;
  method?: string;
  body?: unknown;
  token: () => Promise<string>;
  waking?: Waking;
  sleep?: (ms: number) => Promise<void>;
};

export async function call<T>({
  path,
  method = "GET",
  body,
  token,
  waking,
  sleep = wait,
}: Call): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const answer = await fetch(path, {
      method,
      headers: {
        accept: "application/json",
        authorization: `Bearer ${await token()}`,
        ...(body === undefined ? {} : { "content-type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    if (answer.status === 503 && attempt < RETRIES) {
      waking?.(true);
      await sleep(retryAfter(answer) * 1000);
      continue;
    }
    waking?.(false);

    if (answer.status === 204) return undefined as T;
    const payload = await answer.json().catch(() => null);
    if (!answer.ok) {
      const failure = (payload as ApiError | null)?.error;
      throw new ApiFailure(
        answer.status,
        failure?.code ?? "failed",
        failure?.message ?? "Something went wrong. Please try again.",
      );
    }
    return payload as T;
  }
}

function retryAfter(answer: Response): number {
  const header = Number(answer.headers.get("retry-after"));
  return Number.isFinite(header) && header > 0 ? Math.min(header, 30) : 5;
}

function wait(ms: number): Promise<void> {
  return new Promise((done) => setTimeout(done, ms));
}

// ------------------------------------------------------------------ the calls ---
export function requestUpload(
  ticket: {
    kind: string;
    content_type: string;
    size_bytes: number;
    filename: string;
  },
  token: () => Promise<string>,
  waking?: Waking,
): Promise<UploadTicket> {
  return call<UploadTicket>({
    path: "/api/uploads",
    method: "POST",
    body: ticket,
    token,
    waking,
  });
}

export function getDocument(
  id: string,
  token: () => Promise<string>,
  waking?: Waking,
): Promise<DocumentView> {
  return call<DocumentView>({ path: `/api/documents/${id}`, token, waking });
}

/** The file itself goes straight to storage with the fields the API signed — never through the
 *  API (REQ-002). The browser sends it as a form, because that is what a POST policy takes. */
export async function putFile(
  ticket: UploadTicket,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  const form = new FormData();
  for (const [name, value] of Object.entries(ticket.fields))
    form.append(name, value);
  form.append("file", file);

  await new Promise<void>((done, failed) => {
    const request = new XMLHttpRequest(); // fetch can't report progress on the way up
    request.open("POST", ticket.url);
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable)
        onProgress?.(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () =>
      request.status >= 200 && request.status < 300
        ? done()
        : failed(
            new ApiFailure(
              request.status,
              "upload_failed",
              "The upload didn't finish.",
            ),
          ),
    );
    request.addEventListener("error", () =>
      failed(new ApiFailure(0, "upload_failed", "The upload didn't finish.")),
    );
    request.send(form);
  });
}
