// A tenant's evidence: every photo, notice and WhatsApp export, with what each says about
// itself, its fingerprint, and a way to show it hasn't changed (docs/design/web/evidence.svg;
// T040; REQ-008 to REQ-010).
//
// A lease is not listed: it is read and checked (/lease/:id), not kept as evidence (REQ-010).
// An upload that never arrived (`expired`) isn't evidence of anything, and isn't listed either.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { PlusIcon } from "lucide-react";

import { ApiFailure, listDocuments } from "@/api/client";
import type { DocumentView } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EvidenceCard } from "@/components/EvidenceCard";
import { Notice } from "@/components/Notice";
import { ScreenTitle } from "@/components/ScreenTitle";
import { Button } from "@/components/ui/button";

type State =
  | { name: "loading" }
  | { name: "ready"; documents: DocumentView[] }
  | { name: "failed"; why: string };

const EVIDENCE = new Set(["photo", "notice", "chat"]);

/** Newest first. A file still on its way has no storage time yet, and is newest of all. The
 *  times are ISO-8601 in UTC, so they order as plain text, compared code point by code point:
 *  a locale's collation has no say in it. */
function newestFirst(a: DocumentView, b: DocumentView): number {
  const [x, y] = [a.stored_at ?? "~", b.stored_at ?? "~"];
  return x < y ? 1 : x > y ? -1 : 0;
}

export function Evidence({ waking }: { waking?: (b: boolean) => void }) {
  const { token } = useAuth();
  const [state, setState] = useState<State>({ name: "loading" });

  useEffect(() => {
    let live = true;
    listDocuments(token, waking)
      .then((documents) => {
        if (!live) return;
        setState({
          name: "ready",
          documents: documents
            .filter((d) => EVIDENCE.has(d.kind) && d.status !== "expired")
            .sort(newestFirst),
        });
      })
      .catch((e: unknown) => {
        if (!live) return;
        setState({
          name: "failed",
          why:
            e instanceof ApiFailure
              ? e.message
              : "Your evidence couldn't be loaded. Please try again.",
        });
      });
    return () => {
      live = false;
    };
  }, [token, waking]);

  return (
    <>
      <ScreenTitle title="Evidence">
        Each file was fingerprinted when it arrived. Verify one to show it
        hasn&apos;t changed since.
      </ScreenTitle>

      <Button
        asChild
        size="lg"
        className="mt-4 h-11 w-full text-sm font-semibold"
      >
        <Link to="/evidence/new">
          <PlusIcon aria-hidden="true" />
          Add photos, notices or chats
        </Link>
      </Button>

      {state.name === "loading" ? (
        <p role="status" className="text-note mt-4 text-muted-foreground">
          Loading your evidence…
        </p>
      ) : null}

      {state.name === "failed" ? (
        <Notice
          title="Couldn't load your evidence"
          tone="destructive"
          role="alert"
        >
          {state.why}
        </Notice>
      ) : null}

      {state.name === "ready" && state.documents.length === 0 ? (
        <Notice title="No evidence yet">
          Photos of the damage, the landlord&apos;s notices and your WhatsApp
          chats appear here once you add them, each with its fingerprint.
        </Notice>
      ) : null}

      {state.name === "ready" && state.documents.length > 0 ? (
        <ul className="mt-4 space-y-3">
          {state.documents.map((document) => (
            <li key={document.id}>
              <EvidenceCard document={document} waking={waking} />
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}
