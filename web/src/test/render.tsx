// Rendering one route with a stand-in for whoever is signed in, so a screen's test says what the
// screen does and not how the app is wired.
import { render, type RenderResult } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { AuthContext, type Auth } from "../auth/AuthContext";
import { Layout } from "../components/Layout";
import { EvidenceNew } from "../routes/EvidenceNew";
import { LeaseNew } from "../routes/LeaseNew";
import { SignIn } from "../routes/SignIn";
import { SignUp } from "../routes/SignUp";

export function renderRoute(
  path: string,
  { auth }: { auth: Auth },
): RenderResult {
  return render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={[path]}>
        <Layout>
          <Routes>
            <Route path="/sign-up" element={<SignUp />} />
            <Route path="/sign-in" element={<SignIn />} />
            <Route path="/lease/new" element={<LeaseNew />} />
            <Route path="/evidence/new" element={<EvidenceNew />} />
          </Routes>
        </Layout>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}
