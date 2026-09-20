// The privacy notice's tick (REQ-015). Radix's checkbox, so it is a real checkbox to a screen
// reader and to the keyboard, with the label clickable beside it.
import { Checkbox as Primitive, Label } from "radix-ui";
import { useId } from "react";

type Props = { checked: boolean; onCheckedChange: (checked: boolean) => void; label: string };

export function Checkbox({ checked, onCheckedChange, label }: Props) {
  const id = useId();
  return (
    <div className="mt-4 flex items-center gap-3">
      <Primitive.Root
        id={id}
        checked={checked}
        onCheckedChange={(value) => onCheckedChange(value === true)}
        className="flex size-5 shrink-0 items-center justify-center rounded border border-brand
          bg-white data-[state=checked]:bg-brand"
      >
        <Primitive.Indicator>
          <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden="true">
            <path
              d="M3 8.5 L6.5 12 L13 4.5"
              fill="none"
              stroke="white"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </Primitive.Indicator>
      </Primitive.Root>
      <Label.Root htmlFor={id} className="text-sm text-ink">
        {label}
      </Label.Root>
    </div>
  );
}
