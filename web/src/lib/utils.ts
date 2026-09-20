// shadcn/ui's class helper, in the form it had before the `cn` package existed: clsx to build the
// list, tailwind-merge to let the later utility win. The package that now replaces this pair was
// published nine hours after this project's 7-day dependency cooldown (docs/design/web.md §2), and
// a three-week-old runtime dependency isn't worth two lines.
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
