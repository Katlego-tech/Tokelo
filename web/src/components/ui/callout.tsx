// The panel with a bar down its left edge (the wireframes): what the app is telling the tenant
// rather than asking of them — the privacy notice, "Processing", "Refused".
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

type Props = { title: string; tone?: "brand" | "danger"; children: ReactNode; role?: string };

export function Callout({ title, tone = "brand", children, role }: Props) {
  const bar = tone === "danger" ? "bg-danger" : "bg-brand";
  return (
    <section
      role={role}
      aria-label={title}
      className={cn(
        "relative mt-4 overflow-hidden rounded-[var(--radius-panel)] border bg-surface p-4 pl-5",
        tone === "danger" ? "border-danger" : "border-brand",
      )}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[5px] rounded", bar)} />
      <h2 className="text-sm font-bold text-ink">{title}</h2>
      <div className="mt-2 text-[13px] leading-5 text-muted">{children}</div>
    </section>
  );
}
