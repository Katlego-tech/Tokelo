// The one button (docs/design/web/sign-up.svg, upload.svg): filled for the action a screen is
// for, outlined for the ones beside it, and a link for "I'd rather do the other thing".
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

const button = cva(
  "inline-flex w-full items-center justify-center rounded-[var(--radius-field)] text-[15px] " +
    "font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      look: {
        filled: "bg-brand text-white hover:bg-brand-dark",
        outline: "border border-brand bg-white text-brand hover:bg-surface",
        link: "w-auto text-[14px] font-normal text-brand underline-offset-4 hover:underline",
      },
      size: { tall: "h-11", short: "h-9", bare: "h-auto p-0" },
    },
    defaultVariants: { look: "filled", size: "tall" },
  },
);

type Props = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof button> & { asChild?: boolean };

export function Button({ className, look, size, asChild, ...rest }: Props) {
  const Component = asChild ? Slot.Root : "button";
  return <Component className={cn(button({ look, size }), className)} {...rest} />;
}
