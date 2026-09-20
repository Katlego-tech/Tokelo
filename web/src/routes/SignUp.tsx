// Creating an account (docs/design/web/sign-up.svg; REQ-015, REQ-001).
//
// The privacy notice is not a link a tenant may miss and not a checkbox they tick past: it is
// the first thing on the screen, it says where their lease will be kept and under which law it
// leaves the country, and "Create account" does nothing until they say they have read it.
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/ui/button";
import { Callout } from "../components/ui/callout";
import { Checkbox } from "../components/ui/checkbox";
import { Field } from "../components/ui/field";

export function SignUp() {
  const { signUp, confirm } = useAuth();
  const navigate = useNavigate();
  const [read, setRead] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Whether Cognito has taken the account and is waiting for the emailed code. The screen knows
  // this because it just asked; it doesn't need the session to tell it.
  const [awaitingCode, setAwaitingCode] = useState(false);

  async function attempt(work: () => Promise<void>) {
    setBusy(true);
    setFailure(null);
    try {
      await work();
    } catch (e) {
      // Cognito's own words: "Password did not conform with policy" says more than anything
      // this screen could invent about a password it never sees.
      setFailure(
        e instanceof Error ? e.message : "That didn't work. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (awaitingCode) {
    return (
      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          void attempt(async () => {
            await confirm(code);
            await navigate("/lease/new");
          });
        }}
      >
        <h1 className="mt-6 text-[22px] font-bold text-ink">
          Check your email
        </h1>
        <p className="mt-2 text-sm text-muted">
          We sent a code to {email || "your address"}. Enter it to finish
          creating your account.
        </p>
        <Field
          label="Code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        {failure ? <Refusal message={failure} /> : null}
        <div className="mt-6">
          <Button type="submit" disabled={busy || code.length === 0}>
            Confirm
          </Button>
        </div>
      </form>
    );
  }

  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        void attempt(async () => {
          await signUp(email, password);
          setAwaitingCode(true);
        });
      }}
    >
      <h1 className="mt-6 text-[22px] font-bold text-ink">
        Create your account
      </h1>

      <Callout title="Privacy notice">
        Your documents are stored by AWS in Ireland (EU), which takes them out
        of South Africa under POPIA section 72. Only you can see them, and you
        can delete everything at any time.
      </Callout>

      <Checkbox
        checked={read}
        onCheckedChange={setRead}
        label="I have read the privacy notice"
      />

      <Field
        label="Email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Field
        label="Password"
        hint="(at least 12 characters)"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />

      {failure ? <Refusal message={failure} /> : null}

      <div className="mt-6">
        <Button type="submit" disabled={!read || busy}>
          Create account
        </Button>
      </div>

      <p className="mt-5 text-sm">
        <Link
          to="/sign-in"
          className="text-brand underline-offset-4 hover:underline"
        >
          Already have an account? Sign in
        </Link>
      </p>
    </form>
  );
}

export function Refusal({ message }: { message: string }) {
  return (
    <div role="alert">
      <Callout title="That didn't work" tone="danger">
        {message}
      </Callout>
    </div>
  );
}
