// Signing in (docs/design/web/sign-up.svg, the second panel; REQ-001).
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/ui/button";
import { Field } from "../components/ui/field";
import { Refusal } from "./SignUp";

export function SignIn() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        setBusy(true);
        setFailure(null);
        void signIn(email, password)
          .then(() => navigate("/lease/new"))
          // Cognito says "Incorrect username or password" for both, and so does this screen:
          // which of the two it was is not something a stranger should be able to find out.
          .catch((e: unknown) =>
            setFailure(e instanceof Error ? e.message : "Incorrect email or password."),
          )
          .finally(() => setBusy(false));
      }}
    >
      <h1 className="mt-6 text-[22px] font-bold text-ink">Sign in</h1>
      <Field
        label="Email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Field
        label="Password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      {failure ? <Refusal message={failure} /> : null}
      <div className="mt-6">
        <Button type="submit" disabled={busy}>
          Sign in
        </Button>
      </div>
      <p className="mt-5 text-sm">
        <Link to="/sign-up" className="text-brand underline-offset-4 hover:underline">
          Create an account
        </Link>
      </p>
    </form>
  );
}
