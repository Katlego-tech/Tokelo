// The shapes the API sends (docs/design/api.md §6, "The views"). A field that isn't in a view
// isn't here: the app mirrors the API, it doesn't invent a model of its own (web.md §3).

export type DocumentKind = "lease" | "photo" | "notice" | "chat";
export type DocumentStatus =
  "requested" | "stored" | "processed" | "failed" | "expired";

export type Capture = {
  captured_at: string | "not recorded";
  device: string | "not recorded";
  latitude: number | "not recorded";
  longitude: number | "not recorded";
};

export type DocumentView = {
  id: string;
  kind: DocumentKind;
  status: DocumentStatus;
  content_type: string;
  size_bytes: number;
  sha256: string | null;
  stored_at: string | null;
  failure_reason: string | null;
  capture?: Capture;
};

export type UploadTicket = {
  document_id: string;
  url: string;
  fields: Record<string, string>;
  expires_at: string;
};

export type ApiError = { error: { code: string; message: string } };

export type Config = {
  region: string;
  user_pool_id: string;
  client_id: string;
};

// A lease's flags (api.md §6, `LeaseFlags`). `finding` is there instead of flags when nothing
// matched, and says what was checked — never that the clause is lawful (REQ-007).
export type SectionRef = {
  id: string;
  act: string;
  section: string;
  title: string;
};

export type FlagView = {
  rule_id: string;
  explanation: string;
  sections: SectionRef[];
};

export type ClauseView = {
  label: string;
  first_page: number;
  text: string;
  flags: FlagView[];
  finding?: string;
};

export type LeaseStatus = "reading" | "analysed" | "failed";

export type LeaseFlags = {
  status: LeaseStatus;
  page_count: number;
  unreadable_pages: number[];
  notice: string;
  clauses: ClauseView[];
};
