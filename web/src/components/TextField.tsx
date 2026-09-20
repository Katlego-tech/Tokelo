// A labelled input (docs/design/web/sign-up.svg): shadcn's Label and Input, tied together, with
// the label always above the box. Never a placeholder standing in for a label — it disappears
// exactly when a tenant filling in the form needs it (NFR-009).
import type { ComponentProps, ReactNode } from "react";
import { useId } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = ComponentProps<typeof Input> & {
  label: ReactNode;
  hint?: ReactNode;
};

export function TextField({ label, hint, id, ...rest }: Props) {
  const generated = useId();
  const inputId = id ?? generated;
  return (
    <div className="mt-4 grid gap-1.5">
      <Label
        htmlFor={inputId}
        className="text-xs font-normal text-muted-foreground-foreground"
      >
        {label}
        {hint ? <span> {hint}</span> : null}
      </Label>
      <Input id={inputId} className="h-10" {...rest} />
    </div>
  );
}
