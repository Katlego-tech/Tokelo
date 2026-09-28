// How the evidence screen words what the API sends (docs/design/web.md §6; web/evidence.svg).

import type { DocumentKind, DocumentView } from "@/api/types";

// The API's word for a capture detail a photo doesn't carry (api.md §6), shown as it is (REQ-009).
export const NOT_RECORDED = "not recorded";

export const KIND_NAMES: Record<DocumentKind, string> = {
  lease: "Lease",
  photo: "Photo",
  notice: "Notice",
  chat: "WhatsApp export",
};

/** A time as the app shows it: South African time, to the minute. SAST has no daylight saving,
 *  so it is UTC plus two hours, whatever the phone's own time zone is. */
export function sast(iso: string): string {
  const shifted = new Date(Date.parse(iso) + 2 * 60 * 60 * 1000);
  return `${shifted.toISOString().slice(0, 16).replace("T", " ")} SAST`;
}

/** A digest as the wireframe shows it: its first and last four characters. The whole of it is
 *  in the dossier (part 8) and in any verification that doesn't match. */
export function short(digest: string): string {
  return `${digest.slice(0, 4)}…${digest.slice(-4)}`;
}

/** A record's name on the screens. Tokelo keeps no file names (api.md §6), so a record is named
 *  by what the system does know: its kind and when storage took it (web.md §6). */
export function recordName(document: DocumentView): string {
  const kind = KIND_NAMES[document.kind];
  return document.stored_at
    ? `${kind} · stored ${sast(document.stored_at)}`
    : `${kind} · not stored yet`;
}

/** A photo whose capture details place it somewhere (REQ-009): what the dossier warning counts. */
export function located(document: DocumentView): boolean {
  const capture = document.capture;
  return (
    document.kind === "photo" &&
    capture !== undefined &&
    capture.latitude !== NOT_RECORDED &&
    capture.longitude !== NOT_RECORDED
  );
}
