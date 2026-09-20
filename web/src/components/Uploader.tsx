// Choosing a file and getting it into storage (docs/design/web/upload.svg; REQ-002, REQ-003).
//
// The file's bytes go from the browser straight to S3 with the fields the API signed. Nothing
// here uploads through the API, and nothing here decides what is allowed: the checks below are
// advice, so a tenant hears "that won't work" before spending their data, and the server decides
// for real (api.md §4).
import React, { useRef, useState } from "react";

import { ApiFailure, getDocument, putFile, requestUpload } from "@/api/client";
import type { DocumentKind, DocumentView } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Notice } from "@/components/Notice";
import { MAX_PAGES, joinPhotos } from "@/components/PhotoJoiner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";

export const LIMITS: Record<DocumentKind, { types: string[]; bytes: number }> =
  {
    lease: {
      types: ["application/pdf", "image/jpeg", "image/png"],
      bytes: 20 * 1024 * 1024,
    },
    photo: { types: ["image/jpeg", "image/png"], bytes: 20 * 1024 * 1024 },
    notice: {
      types: ["application/pdf", "image/jpeg", "image/png"],
      bytes: 20 * 1024 * 1024,
    },
    chat: { types: ["text/plain"], bytes: 5 * 1024 * 1024 },
  };

type Stage =
  | { name: "choosing" }
  | { name: "preparing"; photos: number }
  | { name: "uploading"; percent: number }
  | { name: "processing"; document: DocumentView }
  | { name: "done"; document: DocumentView }
  | { name: "refused"; why: string };

export function Uploader({
  kind,
  waking,
}: {
  kind: DocumentKind;
  waking?: (b: boolean) => void;
}) {
  const { token } = useAuth();
  const [stage, setStage] = useState<Stage>({ name: "choosing" });
  const canvas = useRef<HTMLCanvasElement>(null);

  async function send(file: File) {
    const limit = LIMITS[kind];
    if (!limit.types.includes(file.type)) {
      setStage({
        name: "refused",
        why: `${describe(file.type)} aren't accepted: upload ${
          kind === "chat"
            ? "a WhatsApp export as a text file"
            : "a PDF or photos of the pages"
        }.`,
      });
      return;
    }
    if (file.size > limit.bytes) {
      setStage({
        name: "refused",
        why: `That file is ${megabytes(file.size)} MB. The most a ${kind} may be is ${
          limit.bytes / (1024 * 1024)
        } MB.`,
      });
      return;
    }

    try {
      setStage({ name: "uploading", percent: 0 });
      const ticket = await requestUpload(
        {
          kind,
          content_type: file.type,
          size_bytes: file.size,
          filename: file.name,
        },
        token,
        waking,
      );
      await putFile(ticket, file, (percent) =>
        setStage({ name: "uploading", percent }),
      );
      const document = await getDocument(ticket.document_id, token, waking);
      setStage({ name: "processing", document });
    } catch (e) {
      setStage({
        name: "refused",
        why:
          e instanceof ApiFailure
            ? e.message
            : "The upload didn't finish. Please try again.",
      });
    }
  }

  async function choosePhotos(files: File[]) {
    setStage({ name: "preparing", photos: files.length });
    try {
      const sheet = canvas.current ?? window.document.createElement("canvas");
      await send(await joinPhotos(files, sheet));
    } catch (e) {
      setStage({
        name: "refused",
        why:
          e instanceof Error ? e.message : "Those photos couldn't be joined.",
      });
    }
  }

  return (
    <div>
      <p className="mt-2 text-sm text-muted-foreground">
        A PDF, or photos of each page. Photos are joined into one PDF before
        upload (at most {MAX_PAGES} pages and 20 MB).
      </p>

      <Choose
        label="Choose a PDF"
        accept="application/pdf"
        onFiles={(files) => void send(files[0])}
      />
      <Choose
        label="Take or choose photos"
        accept="image/jpeg,image/png"
        multiple
        onFiles={(files) => void choosePhotos(files)}
      />

      {stage.name === "preparing" ? (
        <Tile label="Joining your photos">
          <Badge variant="secondary">{stage.photos} photos → one PDF</Badge>
        </Tile>
      ) : null}

      {stage.name === "uploading" ? (
        <Tile label="Uploading straight to storage">
          <Badge variant="secondary">{stage.percent}%</Badge>
          <Progress
            value={stage.percent}
            aria-label={`Uploading straight to storage: ${stage.percent}%`}
            className="mt-3 h-2"
          />
        </Tile>
      ) : null}

      {stage.name === "processing" || stage.name === "done" ? (
        <Notice title="Processing" role="status">
          We have your file. You can leave this page.
        </Notice>
      ) : null}

      {stage.name === "refused" ? (
        <Notice title="Refused" tone="destructive" role="alert">
          {stage.why}
        </Notice>
      ) : null}

      {stage.name === "choosing" ? (
        <>
          <Separator className="mt-6" />
          <p className="mt-4 text-xs text-muted-foreground">
            Your file goes straight from this phone to storage. It never passes
            through Tokelo&apos;s API, and only you can read it.
          </p>
        </>
      ) : null}

      <canvas ref={canvas} hidden aria-hidden="true" />
    </div>
  );
}

/** A small panel for what is happening to the file right now: a label, and the fact beside it.
 *  The admin blocks' stat tile, at the size a phone can spare. */
function Tile({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-5 rounded-lg border border-border bg-muted/50 px-4 py-3">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function Choose({
  label,
  accept,
  multiple,
  onFiles,
}: {
  label: string;
  accept: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="mt-4">
      <Button
        variant="outline"
        size="lg"
        type="button"
        className="h-11 w-full"
        onClick={() => input.current?.click()}
      >
        {label}
      </Button>
      <input
        ref={input}
        type="file"
        accept={accept}
        multiple={multiple}
        aria-label={label}
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length > 0) onFiles(files);
        }}
      />
    </div>
  );
}

function describe(type: string): string {
  const known: Record<string, string> = {
    "application/msword": "Word documents",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
      "Word documents",
    "image/heic": "HEIC photos",
    "": "Files with no type",
  };
  return known[type] ?? `${type} files`;
}

function megabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1);
}
