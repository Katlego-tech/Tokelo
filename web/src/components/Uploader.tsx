// Choosing a file and getting it into storage (docs/design/web/upload.svg; REQ-002, REQ-003).
//
// The file's bytes go from the browser straight to S3 with the fields the API signed. Nothing
// here uploads through the API, and nothing here decides what is allowed: the checks below are
// advice, so a tenant hears "that won't work" before spending their data, and the server decides
// for real (api.md §4).
import React, {
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { CameraIcon, FileTextIcon, LockIcon, XIcon } from "lucide-react";

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
  // The pages a tenant has chosen but not sent: the wireframe's thumbnail strip. A photographed
  // lease is a stack of separate shots, and the one that came out blurred is easier to see here
  // than after it has been read (docs/design/web/upload.svg).
  | { name: "reviewing"; pages: File[] }
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

  function choosePhotos(files: File[]) {
    if (files.length > MAX_PAGES) {
      setStage({
        name: "refused",
        why: `A lease may be at most ${MAX_PAGES} pages, and you chose ${files.length}.`,
      });
      return;
    }
    setStage({ name: "reviewing", pages: files });
  }

  async function sendPages(pages: File[]) {
    setStage({ name: "preparing", photos: pages.length });
    try {
      const sheet = canvas.current ?? window.document.createElement("canvas");
      await send(await joinPhotos(pages, sheet));
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
      <div className="mt-5 grid gap-2.5">
        <Choose
          label="Choose a PDF"
          accept="application/pdf"
          icon={<FileTextIcon aria-hidden="true" />}
          onFiles={(files) => void send(files[0])}
        />
        <Choose
          label="Take or choose photos"
          accept="image/jpeg,image/png"
          multiple
          icon={<CameraIcon aria-hidden="true" />}
          onFiles={(files) => void choosePhotos(files)}
        />
        <p className="text-caption text-muted-foreground">
          A PDF, or photos of each page joined into one — at most {MAX_PAGES}{" "}
          pages and 20 MB.
        </p>
      </div>

      {stage.name === "reviewing" ? (
        <Pages
          pages={stage.pages}
          onRemove={(index) =>
            setStage({
              name: "reviewing",
              pages: stage.pages.filter((_, n) => n !== index),
            })
          }
          onSend={() => void sendPages(stage.pages)}
        />
      ) : null}

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
          <p className="text-note mt-4 flex gap-2 text-muted-foreground">
            <LockIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>
              Your file goes straight from this phone to storage. It never
              passes through Tokelo&apos;s API, and only you can read it.
            </span>
          </p>
        </>
      ) : null}

      <canvas ref={canvas} hidden aria-hidden="true" />
    </div>
  );
}

/** The pages a tenant photographed, in the order they took them: the wireframe's strip of
 *  thumbnails, each one removable, and the size they will add up to. A lease shot page by page
 *  on a phone always has one that came out blurred, and this is where it is caught. */
function Pages({
  pages,
  onRemove,
  onSend,
}: {
  pages: File[];
  onRemove: (index: number) => void;
  onSend: () => void;
}) {
  const urls = useMemo(
    () => pages.map((page) => URL.createObjectURL(page)),
    [pages],
  );
  useEffect(
    () => () => urls.forEach((url) => URL.revokeObjectURL(url)),
    [urls],
  );
  if (pages.length === 0) return null;

  const total = pages.reduce((bytes, page) => bytes + page.size, 0);
  return (
    <section aria-label="The pages you chose" className="mt-5">
      <div className="flex items-baseline justify-between">
        <p className="text-panel-title">
          {pages.length} {pages.length === 1 ? "page" : "pages"}
        </p>
        <Badge variant="secondary">→ one PDF, {size(total)}</Badge>
      </div>

      <ol className="mt-3 grid grid-cols-4 gap-2">
        {pages.map((page, index) => (
          <li key={`${page.name}-${index}`} className="relative">
            <img
              src={urls[index]}
              alt={`Page ${index + 1}`}
              className="aspect-3/4 w-full rounded-lg border border-border bg-muted object-cover"
            />
            <Button
              type="button"
              variant="secondary"
              size="icon-xs"
              aria-label={`Remove page ${index + 1}`}
              onClick={() => onRemove(index)}
              className="absolute top-1 right-1 rounded-full border border-border bg-card/90 shadow-xs"
            >
              <XIcon aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ol>

      <Button size="lg" className="mt-4 h-11 w-full" onClick={onSend}>
        Upload {pages.length} {pages.length === 1 ? "page" : "pages"}
      </Button>
    </section>
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
  icon,
  onFiles,
}: {
  label: string;
  accept: string;
  multiple?: boolean;
  icon?: ReactNode;
  onFiles: (files: File[]) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div>
      <Button
        variant="outline"
        size="lg"
        type="button"
        className="h-11 w-full"
        onClick={() => input.current?.click()}
      >
        {icon}
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

/** A size as a tenant would say it: kilobytes until it is worth a decimal point in megabytes. */
function size(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${megabytes(bytes)} MB`;
}
