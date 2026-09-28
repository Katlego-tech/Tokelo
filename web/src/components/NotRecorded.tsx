// One capture detail of a photograph (docs/design/web.md §6's tree; REQ-009).
//
// A detail the photo didn't carry says "not recorded", in those words, and quieter than one it
// did: nothing is filled in, and a tenant can see at a glance what the photo can't vouch for.
import { NOT_RECORDED } from "@/lib/evidence";
import { cn } from "@/lib/utils";

export function NotRecorded({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  const missing = value === NOT_RECORDED;
  return (
    <p
      className={cn(
        "text-note",
        missing ? "text-muted-foreground italic" : "text-foreground",
      )}
    >
      {label}: {value}
    </p>
  );
}
