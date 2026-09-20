// A labelled input (docs/design/web/sign-up.svg): the label is always there, above the box, and
// tied to it — never a placeholder standing in for one, which disappears exactly when a tenant
// filling in a form needs it (NFR-009).
import { Label } from "radix-ui";
import type { InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";

import { cn } from "../../lib/cn";

type Props = InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode };

export function Field({ label, hint, className, id, ...rest }: Props) {
  const generated = useId();
  const inputId = id ?? generated;
  const hintId = hint ? `${inputId}-hint` : undefined;
  return (
    <div className="mt-4">
      <Label.Root htmlFor={inputId} className="block text-xs text-muted">
        {label}
        {hint ? <span id={hintId}> {hint}</span> : null}
      </Label.Root>
      <input
        id={inputId}
        aria-describedby={hintId}
        className={cn(
          "mt-1.5 h-10 w-full rounded-[var(--radius-field)] border border-line bg-white px-3",
          "text-sm text-ink placeholder:text-muted",
          className,
        )}
        {...rest}
      />
    </div>
  );
}
