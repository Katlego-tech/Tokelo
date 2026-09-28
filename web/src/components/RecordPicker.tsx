// Choosing a dossier's records (docs/design/web/dossier.svg; web.md §6's tree).
//
// Only finished records are offered: the API refuses anything still being read (api.md §6),
// and offering it would be offering a refusal. Each is named as the evidence screen names it,
// by kind and storage time, since Tokelo keeps no file names.
import type { DocumentView } from "@/api/types";
import { LocationWarning } from "@/components/LocationWarning";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { located, recordName } from "@/lib/evidence";

export function RecordPicker({
  records,
  chosen,
  onChange,
}: {
  records: DocumentView[];
  chosen: Set<string>;
  onChange: (chosen: Set<string>) => void;
}) {
  function toggle(id: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(id);
    else next.delete(id);
    onChange(next);
  }

  const locatedCount = records.filter(
    (r) => chosen.has(r.id) && located(r),
  ).length;

  return (
    <fieldset className="mt-4">
      <legend className="text-panel-title text-foreground">
        What goes into it
      </legend>
      <ul className="mt-2 space-y-1">
        {records.map((record) => {
          const id = `record-${record.id}`;
          return (
            <li key={record.id} className="flex items-center gap-3 py-1.5">
              <Checkbox
                id={id}
                checked={chosen.has(record.id)}
                onCheckedChange={(value) => toggle(record.id, value === true)}
              />
              <Label htmlFor={id} className="text-body font-normal">
                {recordName(record)}
              </Label>
            </li>
          );
        })}
      </ul>
      <LocationWarning count={locatedCount} />
    </fieldset>
  );
}
