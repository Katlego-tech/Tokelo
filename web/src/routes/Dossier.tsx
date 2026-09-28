// Building a dossier (docs/design/web/dossier.svg; T044; REQ-013).
//
// Choose the records, see which photos give away where they were taken, build, wait, download.
// The rules are the server's (api.md §6): an empty or oversized choice is refused with its
// reason, which is shown as it is, so the screen and the API can't disagree about them.
//
// The download link lasts five minutes (NFR-006). A tenant who lingers gets a fresh one when
// they tap it, rather than a link that has quietly died.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import {
  ApiFailure,
  getDossier,
  listDocuments,
  requestDossier,
} from "@/api/client";
import type { DocumentView, DossierView } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Notice } from "@/components/Notice";
import { RecordPicker } from "@/components/RecordPicker";
import { ScreenTitle } from "@/components/ScreenTitle";
import { Button } from "@/components/ui/button";
import { short } from "@/lib/evidence";

/** How often to ask how the dossier is coming along. The worker takes seconds for most, and up
 *  to a couple of minutes for a long chat (dossier.md §4). */
export const POLL_MS = 3000;

type Building =
  | { name: "choosing" }
  | { name: "asking" }
  | { name: "building"; id: string }
  | { name: "ready"; dossier: DossierView }
  | { name: "failed"; why: string };

function why(e: unknown, otherwise: string): string {
  return e instanceof ApiFailure ? e.message : otherwise;
}

function megabytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function Dossier({
  waking,
  pollMs = POLL_MS,
}: {
  waking?: (b: boolean) => void;
  pollMs?: number;
}) {
  const { token } = useAuth();
  const [records, setRecords] = useState<DocumentView[] | null>(null);
  const [loadFailed, setLoadFailed] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [building, setBuilding] = useState<Building>({ name: "choosing" });
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    listDocuments(token, waking)
      .then((documents) => {
        if (!live.current) return;
        setRecords(
          documents
            .filter((d) => d.status === "processed" && d.sha256)
            .sort((a, b) =>
              (a.stored_at ?? "") < (b.stored_at ?? "") ? -1 : 1,
            ),
        );
      })
      .catch((e: unknown) => {
        if (live.current)
          setLoadFailed(
            why(e, "Your records couldn't be loaded. Please try again."),
          );
      });
    return () => {
      live.current = false;
    };
  }, [token, waking]);

  // While it builds, ask after it until it is ready or has failed.
  const buildingId = building.name === "building" ? building.id : null;
  useEffect(() => {
    if (!buildingId) return;
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const ask = async () => {
      try {
        const dossier = await getDossier(buildingId, token, waking);
        if (stopped) return;
        if (dossier.status === "ready") setBuilding({ name: "ready", dossier });
        else if (dossier.status === "failed")
          setBuilding({
            name: "failed",
            why: dossier.failure_reason ?? "The dossier couldn't be built.",
          });
        else timer = setTimeout(ask, pollMs);
      } catch (e) {
        if (!stopped)
          setBuilding({
            name: "failed",
            why: why(e, "The dossier couldn't be checked."),
          });
      }
    };
    timer = setTimeout(ask, 0);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [buildingId, pollMs, token, waking]);

  async function build() {
    setBuilding({ name: "asking" });
    try {
      // In the order they are listed, which is the order they were stored.
      const ids = (records ?? [])
        .filter((r) => chosen.has(r.id))
        .map((r) => r.id);
      const id = await requestDossier(ids, token, waking);
      setBuilding({ name: "building", id });
    } catch (e) {
      setBuilding({
        name: "failed",
        why: why(e, "The dossier couldn't be started."),
      });
    }
  }

  /** The link lasts five minutes. If it has run out, fetch the dossier again for a fresh one. */
  const download = useCallback(
    async (
      event: React.MouseEvent<HTMLAnchorElement>,
      dossier: DossierView,
    ) => {
      const expires = Date.parse(dossier.expires_at ?? "");
      if (Number.isFinite(expires) && expires - Date.now() > 10_000) return;
      event.preventDefault();
      const fresh = await getDossier(dossier.id, token, waking);
      if (fresh.download_url) window.location.assign(fresh.download_url);
    },
    [token, waking],
  );

  return (
    <>
      <ScreenTitle title="Build a dossier">
        One PDF of your case, for the Rental Housing Tribunal or the Small
        Claims Court: an index, a timeline, and every file with its fingerprint.
      </ScreenTitle>

      {loadFailed ? (
        <Notice
          title="Couldn't load your records"
          tone="destructive"
          role="alert"
        >
          {loadFailed}
        </Notice>
      ) : null}

      {records === null && !loadFailed ? (
        <p role="status" className="text-note mt-4 text-muted-foreground">
          Loading your records…
        </p>
      ) : null}

      {records !== null && records.length === 0 ? (
        <Notice title="Nothing to put in a dossier yet">
          A dossier is built from your lease and your evidence once they have
          been read.{" "}
          <Link className="underline" to="/evidence/new">
            Add evidence
          </Link>{" "}
          or{" "}
          <Link className="underline" to="/lease/new">
            upload your lease
          </Link>
          .
        </Notice>
      ) : null}

      {records !== null && records.length > 0 ? (
        <>
          <RecordPicker
            records={records}
            chosen={chosen}
            onChange={setChosen}
          />
          <Button
            type="button"
            size="lg"
            className="mt-4 h-11 w-full text-sm font-semibold"
            disabled={
              building.name === "asking" || building.name === "building"
            }
            onClick={() => void build()}
          >
            Build dossier
          </Button>
        </>
      ) : null}

      {building.name === "building" || building.name === "asking" ? (
        <Notice title="Building your dossier" role="status">
          This takes a few seconds, and up to a couple of minutes for a long
          chat.
        </Notice>
      ) : null}

      {building.name === "failed" ? (
        <Notice
          title="The dossier wasn't built"
          tone="destructive"
          role="alert"
        >
          {building.why}
        </Notice>
      ) : null}

      {building.name === "ready" ? (
        <Ready dossier={building.dossier} onDownload={download} />
      ) : null}
    </>
  );
}

function Ready({
  dossier,
  onDownload,
}: {
  dossier: DossierView;
  onDownload: (e: React.MouseEvent<HTMLAnchorElement>, d: DossierView) => void;
}) {
  return (
    <>
      <section
        aria-label="Ready"
        className="mt-4 rounded-lg border border-l-4 border-verified bg-muted/60 px-4 py-3"
      >
        <h2 className="text-panel-title text-foreground">Ready</h2>
        <p className="text-note mt-1 text-muted-foreground">
          Dispute dossier, {dossier.page_count} pages,{" "}
          {megabytes(dossier.size_bytes ?? 0)}
        </p>
        {dossier.sha256 ? (
          <p
            className="text-note font-mono text-muted-foreground"
            title={dossier.sha256}
          >
            SHA-256: {short(dossier.sha256)}
          </p>
        ) : null}
      </section>
      {dossier.download_url ? (
        <Button
          asChild
          variant="outline"
          className="mt-3 h-11 w-full border-primary text-sm font-semibold text-primary hover:bg-accent hover:text-accent-foreground"
        >
          <a
            href={dossier.download_url}
            onClick={(event) => onDownload(event, dossier)}
          >
            Download (link valid for 5 minutes)
          </a>
        </Button>
      ) : null}
    </>
  );
}
