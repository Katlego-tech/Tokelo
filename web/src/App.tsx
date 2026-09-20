// The app shell (docs/design/web.md §6). It loads the settings the image was given at run time,
// configures Cognito from them, and puts the screens behind whoever is signed in (ADR-0010).
import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router";

import { loadConfig } from "./api/client";
import type { Config } from "./api/types";
import { AuthProvider } from "./auth/AuthProvider";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { EvidenceNew } from "./routes/EvidenceNew";
import { LeaseNew } from "./routes/LeaseNew";
import { SignIn } from "./routes/SignIn";
import { SignUp } from "./routes/SignUp";

export function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    loadConfig()
      .then(setConfig)
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return (
      <main className="mx-auto max-w-md p-5">
        <h1 className="text-xl font-bold text-foreground">
          Tokelo isn&apos;t available
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This copy of the app has no settings to sign you in with. Please try
          again later.
        </p>
      </main>
    );
  }
  if (!config)
    return <p className="p-5 text-sm text-muted-foreground">Loading…</p>;

  return (
    <AuthProvider config={config}>
      <Screens />
    </AuthProvider>
  );
}

function Screens() {
  const { status } = useAuth();
  if (status === "loading")
    return <p className="p-5 text-sm text-muted-foreground">Loading…</p>;

  return (
    <Layout>
      <Routes>
        <Route path="/sign-up" element={<SignUp />} />
        <Route path="/sign-in" element={<SignIn />} />
        <Route
          path="/lease/new"
          element={<SignedIn>{<LeaseNew />}</SignedIn>}
        />
        <Route
          path="/evidence/new"
          element={<SignedIn>{<EvidenceNew />}</SignedIn>}
        />
        <Route
          path="*"
          element={
            <Navigate
              to={status === "signed-in" ? "/lease/new" : "/sign-in"}
              replace
            />
          }
        />
      </Routes>
    </Layout>
  );
}

function SignedIn({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  return status === "signed-in" ? (
    <>{children}</>
  ) : (
    <Navigate to="/sign-in" replace />
  );
}
