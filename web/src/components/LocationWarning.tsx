// "N selected photos include their location" (docs/design/web.md §6's wording; §Threats).
//
// A dossier goes to the other side of a dispute. A photograph that recorded where it was taken
// usually recorded the tenant's home, and the dossier prints it (dossier.md §6, part 5). So the
// tenant is told before building, while unticking the photo is still one tap away.
import { MapPinIcon } from "lucide-react";

export function LocationWarning({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <p
      role="status"
      className="text-note mt-4 flex items-center gap-2 rounded-lg border border-caution bg-background px-3 py-2.5 font-semibold text-caution"
    >
      <MapPinIcon aria-hidden="true" className="size-4 shrink-0" />
      {count === 1
        ? "1 selected photo includes its location"
        : `${count} selected photos include their location`}
    </p>
  );
}
