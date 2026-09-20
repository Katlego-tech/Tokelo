// Joining class names, as shadcn/ui's components do: later Tailwind utilities win over earlier
// ones instead of both landing in the class list and the cascade deciding.
import { twMerge } from "tailwind-merge";

export type ClassValue = string | false | null | undefined;

export function cn(...classes: ClassValue[]): string {
  return twMerge(classes.filter(Boolean).join(" "));
}
