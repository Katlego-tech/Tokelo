// One evidence file as the tenant sees it (docs/design/web/evidence.svg; REQ-008 to REQ-010).
//
// The wireframe titles a card "Kitchen wall · photo". Tokelo keeps no file names (api.md §6),
// so a card is titled by what the system does know: its kind and when storage took it. Below
// that is what a photo says about itself, the digest, and the way to check it (web.md §6).
//
// Where the photo was taken is said to be "recorded", never shown: the coordinates are the
// tenant's home, and this screen has no reason to put them on it.
import { CircleDotDashedIcon } from "lucide-react";

import type { DocumentView } from "@/api/types";
import { NotRecorded } from "@/components/NotRecorded";
import { Notice } from "@/components/Notice";
import { VerifyButton } from "@/components/VerifyButton";
import { Card, CardContent } from "@/components/ui/card";
import { NOT_RECORDED, recordName, sast, short } from "@/lib/evidence";

export function EvidenceCard({
  document,
  waking,
}: {
  document: DocumentView;
  waking?: (b: boolean) => void;
}) {
  const named = recordName(document);
  const capture = document.capture;
  return (
    <article aria-label={named}>
      <Card className="gap-0 border-l-4 border-l-border bg-muted/60 py-0 shadow-none">
        <CardContent className="px-4 py-3.5">
          <h2 className="text-panel-title text-foreground">{named}</h2>

          {document.kind === "photo" && capture ? (
            <div className="mt-1.5 space-y-0.5">
              <NotRecorded
                label="Captured"
                value={
                  capture.captured_at === NOT_RECORDED
                    ? NOT_RECORDED
                    : sast(capture.captured_at)
                }
              />
              <NotRecorded label="Device" value={capture.device} />
              <NotRecorded
                label="Location"
                value={
                  capture.latitude === NOT_RECORDED ||
                  capture.longitude === NOT_RECORDED
                    ? NOT_RECORDED
                    : "recorded"
                }
              />
            </div>
          ) : null}

          {document.sha256 ? (
            <p
              className="text-note mt-1.5 font-mono text-muted-foreground"
              title={document.sha256}
            >
              SHA-256: {short(document.sha256)}
            </p>
          ) : null}

          {document.status === "requested" ? (
            <p className="text-note mt-1.5 flex items-center gap-1.5 text-muted-foreground">
              <CircleDotDashedIcon aria-hidden="true" className="size-3.5" />
              Waiting for the file to arrive
            </p>
          ) : null}
          {document.status === "stored" ? (
            <p className="text-note mt-1.5 flex items-center gap-1.5 text-muted-foreground">
              <CircleDotDashedIcon aria-hidden="true" className="size-3.5" />
              Fingerprinted; still being read
            </p>
          ) : null}
          {document.status === "failed" ? (
            <Notice
              title="Couldn't be processed"
              tone="destructive"
              role="status"
            >
              {document.failure_reason ??
                "This file couldn't be processed. Please upload it again."}
            </Notice>
          ) : null}

          {document.sha256 ? (
            <VerifyButton documentId={document.id} waking={waking} />
          ) : null}
        </CardContent>
      </Card>
    </article>
  );
}
