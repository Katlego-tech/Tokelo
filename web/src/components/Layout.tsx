// The frame every screen sits in (docs/design/web.md §6's tree, and the wireframes).
//
// A light canvas with the screen on a white card, the way shadcn's admin blocks compose a page:
// the card gives each screen an edge, so a form, a notice and a progress bar read as one thing
// on a phone rather than as items floating on a page. The header keeps the name and, when a
// tenant is signed in, the way out.
import { type ReactNode } from "react";
import { Link } from "react-router";

import { useAuth } from "@/auth/AuthContext";
import { LegalNotice } from "@/components/LegalNotice";
import { WakingBanner } from "@/components/WakingBanner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export function Layout({
  waking = false,
  children,
}: {
  waking?: boolean;
  children: ReactNode;
}) {
  const { status, signOut } = useAuth();
  return (
    <div className="min-h-dvh bg-muted/60">
      <header className="sticky top-0 z-10 bg-header">
        <div className="mx-auto flex max-w-md items-center justify-between px-5 py-3.5">
          <Link to="/" className="text-lg font-bold tracking-tight text-white">
            Tokelo
          </Link>
          {status === "signed-in" ? (
            <Button
              variant="ghost"
              onClick={() => void signOut()}
              className="text-white hover:bg-white/10 hover:text-white"
            >
              Sign out
            </Button>
          ) : null}
        </div>
      </header>

      <div className="mx-auto max-w-md px-4 pt-4 pb-10">
        <WakingBanner waking={waking} />
        <Card className="mt-4 gap-0 py-0 shadow-xs">
          <CardContent className="px-5 py-6">{children}</CardContent>
        </Card>
        <LegalNotice />
      </div>
    </div>
  );
}
