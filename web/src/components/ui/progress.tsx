// How far an upload has got (docs/design/web/upload.svg). Radix's progress, so the percentage is
// announced rather than only drawn.
import { Progress as Primitive } from "radix-ui";

export function Progress({ value, label }: { value: number; label: string }) {
  return (
    <div className="mt-4">
      <p className="text-xs text-muted">{label}</p>
      <Primitive.Root
        value={value}
        max={100}
        aria-label={label}
        className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-line"
      >
        <Primitive.Indicator
          className="h-full rounded-full bg-brand transition-[width]"
          style={{ width: `${value}%` }}
        />
      </Primitive.Root>
    </div>
  );
}
