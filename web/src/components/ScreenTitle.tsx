// A screen's heading and the line under it (the wireframes; the section headers in shadcn's
// admin blocks). Every screen opens the same way, so a tenant always knows what this one is for
// before anything asks them for something.
import type { ReactNode } from "react";

export function ScreenTitle({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <header>
      <h1 className="text-xl font-bold tracking-tight text-foreground">
        {title}
      </h1>
      {children ? (
        <p className="mt-1.5 text-sm text-muted-foreground">{children}</p>
      ) : null}
    </header>
  );
}
