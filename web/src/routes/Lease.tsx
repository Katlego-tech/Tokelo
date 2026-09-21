// A lease's flags (docs/design/web/lease.svg; REQ-004 to REQ-007).
//
// The screen a tenant came for. Three things it must never do, in the order they'd hurt:
//
// 1. **Never say a clause is lawful.** A clause nothing matched carries the API's own finding —
//    what was checked, not a verdict (REQ-007). The words come down the wire so the screen and
//    the rules cannot drift apart.
// 2. **Never show half a lease.** While the workers are still reading, the API answers 409 and
//    this waits, because a lease missing three of its clauses reads as a lease with fewer
//    problems than it has.
// 3. **Never hide a page it couldn't read.** The pages that defeated the reader are named by
//    number, at the top, before any flag (REQ-004) — a tenant should know what wasn't checked
//    before they read what was.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { AlertTriangleIcon, ScaleIcon } from "lucide-react";

import { ApiFailure, getLeaseFlags } from "@/api/client";
import type { ClauseView, LeaseFlags, SectionRef } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Notice } from "@/components/Notice";
import { ScreenTitle } from "@/components/ScreenTitle";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

/** How often to ask again while the lease is still being read. NFR-003 promises flags inside
 *  two minutes, so this is often enough to feel immediate and rare enough to cost nothing. */
export const POLL_MS = 5000;

type State =
  | { name: "reading" }
  | { name: "ready"; lease: LeaseFlags }
  | { name: "missing" }
  | { name: "failed"; why: string };

export function Lease({
  waking,
  pollMs = POLL_MS,
}: {
  waking?: (b: boolean) => void;
  pollMs?: number;
}) {
  const { id = "" } = useParams();
  const { token } = useAuth();
  const [state, setState] = useState<State>({ name: "reading" });
  // The screen unmounts while a timer is pending whenever a tenant navigates away mid-read.
  const live = useRef(true);

  const ask = useCallback(async () => {
    try {
      const lease = await getLeaseFlags(id, token, waking);
      if (live.current) setState({ name: "ready", lease });
      return true;
    } catch (e) {
      if (!live.current) return true;
      if (e instanceof ApiFailure && e.status === 409) return false; // still reading
      setState(
        e instanceof ApiFailure && e.status === 404
          ? { name: "missing" }
          : {
              name: "failed",
              why:
                e instanceof ApiFailure
                  ? e.message
                  : "Your lease couldn't be loaded. Please try again.",
            },
      );
      return true;
    }
  }, [id, token, waking]);

  useEffect(() => {
    live.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const again = async () => {
      if (!(await ask()) && live.current) timer = setTimeout(again, pollMs);
    };
    void again();
    return () => {
      live.current = false;
      clearTimeout(timer);
    };
  }, [ask, pollMs]);

  if (state.name === "reading")
    return (
      <>
        <ScreenTitle title="Your lease" />
        <Notice title="Reading your lease" role="status">
          We are reading every page and checking its clauses. This usually takes
          under two minutes — you can leave this page and come back.
        </Notice>
      </>
    );

  if (state.name === "missing")
    return (
      <>
        <ScreenTitle title="Your lease" />
        <Notice title="No such lease" tone="destructive" role="alert">
          We have no lease by that name for your account.{" "}
          <Link className="underline" to="/lease/new">
            Upload one
          </Link>
          .
        </Notice>
      </>
    );

  if (state.name === "failed")
    return (
      <>
        <ScreenTitle title="Your lease" />
        <Notice
          title="Couldn't load your lease"
          tone="destructive"
          role="alert"
        >
          {state.why}
        </Notice>
      </>
    );

  const { lease } = state;
  const flagged = lease.clauses.filter((c) => c.flags.length > 0).length;

  return (
    <>
      <ScreenTitle title="Your lease">
        {lease.status === "analysed"
          ? `${flagged === 0 ? "No" : flagged} clause${flagged === 1 ? "" : "s"} matched these checks.`
          : "We could not read this file."}
      </ScreenTitle>

      <p className="text-note mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
        <Badge
          variant={lease.status === "analysed" ? "secondary" : "destructive"}
        >
          {lease.status === "analysed" ? "Analysed" : "Failed"}
        </Badge>
        <span aria-hidden="true">·</span>
        <span>
          {lease.page_count} page{lease.page_count === 1 ? "" : "s"}
        </span>
      </p>

      {lease.unreadable_pages.length > 0 ? (
        <Notice title={unreadableTitle(lease.unreadable_pages)} role="status">
          Nothing on {lease.unreadable_pages.length === 1 ? "it" : "them"} was
          guessed at, so those clauses were not checked. A clearer photograph of{" "}
          {lease.unreadable_pages.length === 1 ? "that page" : "those pages"}{" "}
          would let us read{" "}
          {lease.unreadable_pages.length === 1 ? "it" : "them"}.
        </Notice>
      ) : null}

      <p className="text-note mt-4 flex gap-2 text-muted-foreground">
        <ScaleIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>{lease.notice}</span>
      </p>

      <Separator className="mt-5" />

      <ol className="mt-5 space-y-3">
        {lease.clauses.map((clause) => (
          <li key={clause.label}>
            <ClauseCard clause={clause} />
          </li>
        ))}
      </ol>
    </>
  );
}

function unreadableTitle(pages: number[]): string {
  const list =
    pages.length === 1
      ? `Page ${pages[0]}`
      : `Pages ${pages.slice(0, -1).join(", ")} and ${pages[pages.length - 1]}`;
  return `${list} couldn't be read`;
}

function ClauseCard({ clause }: { clause: ClauseView }) {
  const flagged = clause.flags.length > 0;
  return (
    <Card className={flagged ? "border-l-4 border-l-primary" : undefined}>
      <CardContent className="px-4 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-panel-title text-foreground">
            Clause {clause.label}
          </h2>
          {flagged ? (
            <Badge variant="outline" className="gap-1 border-primary">
              <AlertTriangleIcon aria-hidden="true" className="size-3" />
              Flagged
            </Badge>
          ) : null}
          <span className="text-caption ml-auto text-muted-foreground">
            Page {clause.first_page}
          </span>
        </div>

        {/* The lease's own words. api.md §6 sends them with every clause, and a tenant reading
            "Clause 12 · flagged" with no sight of clause 12 would have to fetch the paper. */}
        <p className="text-note mt-2 border-l-2 border-border pl-3 text-muted-foreground italic">
          {clause.text}
        </p>

        {flagged ? (
          <ul className="mt-3 space-y-3">
            {clause.flags.map((flag) => (
              <li key={flag.rule_id}>
                <p className="text-body text-foreground">{flag.explanation}</p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {flag.sections.map((section) => (
                    <li key={section.id}>
                      <Section section={section} />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-note mt-3 text-muted-foreground">
            {/* The API's own words, never "lawful" and never "fine" (REQ-007). */}
            {capitalised(clause.finding ?? "")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** What a flag rests on, in full: a tenant can look this up, which is the whole point of
 *  citing it (REQ-006). */
function Section({ section }: { section: SectionRef }) {
  return (
    <span className="block rounded-md border border-border bg-muted/50 px-2.5 py-1.5">
      <span className="text-caption block font-medium text-foreground">
        Section {section.section} · {section.title}
      </span>
      <span className="text-caption block text-muted-foreground">
        {section.act}
      </span>
    </span>
  );
}

function capitalised(sentence: string): string {
  return sentence ? sentence[0].toUpperCase() + sentence.slice(1) : sentence;
}
