// "Delete my account" (docs/design/web/account.svg; api.md §4 "Deleting an account"; REQ-016).
//
// Two steps, in the design's order. The API deletes the files and records first; only then does
// this delete the sign-in, with the tenant's own token. If the first step fails, nothing else is
// touched and the tenant can try again. If the second fails, they are told exactly that, and
// trying again is safe: the API finds nothing left and answers as before.
//
// Typing DELETE is the guard against a stray tap (web.md § Threats), and the button does nothing
// until it is typed exactly.
import { useState } from "react";
import { useNavigate } from "react-router";

import { ApiFailure, deleteAccount as deleteEverything } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Notice } from "@/components/Notice";
import { TextField } from "@/components/TextField";
import { Button } from "@/components/ui/button";

const WORD = "DELETE";

export function DeleteAccount({ waking }: { waking?: (b: boolean) => void }) {
  const { token, deleteAccount } = useAuth();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setFailure(null);
    try {
      await deleteEverything(token, waking);
    } catch (e) {
      setFailure(
        e instanceof ApiFailure
          ? e.message
          : "Your account couldn't be deleted. Please try again.",
      );
      setBusy(false);
      return;
    }
    try {
      await deleteAccount();
    } catch {
      setFailure(
        "Your files and records are deleted, but your sign-in couldn't be removed. Please try again.",
      );
      setBusy(false);
      return;
    }
    await navigate("/sign-in", { state: { deleted: true } });
  }

  return (
    <section aria-labelledby="delete-title" className="mt-6">
      <h2 id="delete-title" className="text-panel-title text-destructive">
        Delete my account
      </h2>
      <p className="text-note mt-1.5 text-muted-foreground">
        Deletes your files, leases, evidence and dossiers. The audit log keeps
        its entries, without your identity. This can&apos;t be undone.
      </p>
      <TextField
        label={`Type ${WORD} to confirm`}
        value={typed}
        autoComplete="off"
        onChange={(e) => setTyped(e.target.value)}
      />
      <Button
        type="button"
        variant="destructive"
        size="lg"
        className="mt-3 h-11 w-full border border-destructive text-sm font-semibold"
        disabled={typed !== WORD || busy}
        onClick={() => void remove()}
      >
        Delete my account
      </Button>
      {failure ? (
        <Notice title="Not deleted" tone="destructive" role="alert">
          {failure}
        </Notice>
      ) : null}
    </section>
  );
}
