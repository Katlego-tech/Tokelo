// A panel that tells the tenant something rather than asking of them — the privacy notice,
// "Processing", "Refused" (the wireframes' left-barred boxes).
//
// shadcn's Alert with a bar down its left edge: the bar is what makes the three read as one
// family across the screens, and the tone is the only thing that changes.
import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

type Props = {
  title: string;
  tone?: "default" | "destructive";
  /** What this panel is to a screen reader. shadcn's Alert is `role="alert"`, which interrupts
   *  whatever is being read — right for a refusal, wrong for a privacy notice that was on the
   *  page before the tenant arrived. So each use says which it is, and the default is the quiet
   *  one (NFR-009). */
  role?: "region" | "status" | "alert";
  children: ReactNode;
};

export function Notice({
  title,
  tone = "default",
  role = "region",
  children,
}: Props) {
  return (
    <Alert
      variant={tone}
      role={role}
      aria-label={title}
      className={cn(
        // A panel inside the screen's sheet, so it needs its own surface to sit on.
        "mt-4 overflow-hidden border-l-4 bg-muted/60 px-4 py-3",
        tone === "destructive" ? "border-destructive" : "border-primary",
      )}
    >
      <AlertTitle className="text-panel-title">{title}</AlertTitle>
      <AlertDescription className="text-note">{children}</AlertDescription>
    </Alert>
  );
}
