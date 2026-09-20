// The frame every screen sits in (docs/design/web.md §6's tree, and the wireframes): the name,
// the menu, whatever the screen is, the waking banner and the legal notice.
import { type ReactNode } from "react";
import { Link } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { LegalNotice } from "./LegalNotice";
import { WakingBanner } from "./WakingBanner";

export function Layout({ waking = false, children }: { waking?: boolean; children: ReactNode }) {
  const { status, signOut } = useAuth();
  return (
    <div className="mx-auto min-h-dvh max-w-md bg-white">
      <header className="flex items-center justify-between bg-ink px-5 py-4">
        <Link to="/" className="text-lg font-bold text-white">
          Tokelo
        </Link>
        {status === "signed-in" ? (
          <button type="button" onClick={() => void signOut()} className="text-sm text-white">
            Sign out
          </button>
        ) : null}
      </header>
      <main className="px-5 pb-10">
        <WakingBanner waking={waking} />
        {children}
        <LegalNotice />
      </main>
    </div>
  );
}
