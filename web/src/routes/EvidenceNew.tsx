// Uploading evidence: a photo of the damp, a notice from the landlord, a WhatsApp export
// (docs/design/web.md §6; REQ-002).
import { useState } from "react";

import type { DocumentKind } from "../api/types";
import { Uploader } from "../components/Uploader";
import { Button } from "../components/ui/button";

const KINDS: { kind: DocumentKind; label: string }[] = [
  { kind: "photo", label: "A photo" },
  { kind: "notice", label: "A notice" },
  { kind: "chat", label: "A WhatsApp export" },
];

export function EvidenceNew() {
  const [kind, setKind] = useState<DocumentKind>("photo");
  return (
    <>
      <h1 className="mt-6 text-[22px] font-bold text-ink">Add evidence</h1>
      <div className="mt-4 flex gap-2" role="group" aria-label="What are you adding?">
        {KINDS.map((choice) => (
          <Button
            key={choice.kind}
            type="button"
            size="short"
            look={kind === choice.kind ? "filled" : "outline"}
            aria-pressed={kind === choice.kind}
            onClick={() => setKind(choice.kind)}
          >
            {choice.label}
          </Button>
        ))}
      </div>
      <Uploader kind={kind} />
    </>
  );
}
