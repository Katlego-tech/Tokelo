// How the evidence screen words what the API sends (docs/design/web.md §6; web/evidence.svg).

import type { DocumentKind } from "@/api/types";

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
