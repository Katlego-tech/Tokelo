// "Verify this file" and what it found (docs/design/web/evidence.svg; REQ-010).
//
// The API reads the stored file by the version its digest was taken of, hashes it again and
// compares (api.md §6). This only asks and says the answer. A match is said quietly, in green. A
// file that no longer matches is said as an alert, with both digests, since what differs is the
// whole point of looking.
import { useState } from "react";
import { ShieldAlertIcon, ShieldCheckIcon } from "lucide-react";

import { ApiFailure, verifyEvidence } from "@/api/client";
import type { Verification } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { sast } from "@/lib/evidence";

type State =
  | { name: "idle" }
  | { name: "checking" }
  | { name: "checked"; verification: Verification }
  | { name: "failed"; why: string };

export function VerifyButton({
  documentId,
  waking,
}: {
  documentId: string;
  waking?: (b: boolean) => void;
}) {
  const { token } = useAuth();
  const [state, setState] = useState<State>({ name: "idle" });

  async function verify() {
    setState({ name: "checking" });
    try {
      const verification = await verifyEvidence(documentId, token, waking);
      setState({ name: "checked", verification });
    } catch (e) {
      setState({
        name: "failed",
        why:
          e instanceof ApiFailure
            ? e.message
            : "This file couldn't be checked. Please try again.",
      });
    }
  }

  return (
    <div className="mt-3">
      <Button
        type="button"
        variant="outline"
        className="h-11 w-full border-primary text-sm font-semibold text-primary hover:bg-accent hover:text-accent-foreground"
        disabled={state.name === "checking"}
        onClick={() => void verify()}
      >
        {state.name === "checking" ? "Checking…" : "Verify this file"}
      </Button>

      <div aria-live="polite">
        {state.name === "checked" && state.verification.matches ? (
          <p className="text-note mt-2 flex gap-2 rounded-lg border border-verified bg-background px-3 py-2.5 text-verified">
            <ShieldCheckIcon
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0"
            />
            <span>
              <span className="block font-semibold">
                Unchanged: matches its stored digest
              </span>
              <span className="block">
                Checked {sast(state.verification.verified_at)}
              </span>
            </span>
          </p>
        ) : null}
        {state.name === "failed" ? (
          <p className="text-note mt-2 text-destructive">{state.why}</p>
        ) : null}
      </div>
      {state.name === "checked" && !state.verification.matches ? (
        <div
          role="alert"
          className="text-note mt-2 flex gap-2 rounded-lg border border-destructive bg-background px-3 py-2.5 text-destructive"
        >
          <ShieldAlertIcon
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0"
          />
          <div className="min-w-0">
            <p className="font-semibold">
              Changed: doesn&apos;t match its stored digest
            </p>
            <p className="mt-1 text-foreground">
              Checked {sast(state.verification.verified_at)}. The file Tokelo
              holds no longer hashes to the digest taken when it was stored.
            </p>
            <dl className="mt-2 space-y-1 font-mono text-[0.6875rem] break-all text-foreground">
              <div>
                <dt className="font-sans text-muted-foreground">Recorded</dt>
                <dd>{state.verification.recorded_sha256}</dd>
              </div>
              <div>
                <dt className="font-sans text-muted-foreground">Now</dt>
                <dd>{state.verification.computed_sha256}</dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </div>
  );
}
