// Asking a rights question (docs/design/web/navigator.svg; T047; REQ-014).
//
// The answers are written, not generated (ADR-0006): the API matches the question to a curated
// topic or says none covers it. This screen shows either reply as the API sent it. It never
// rewords an answer, and never offers one of its own when the API says "outside".
import { useState } from "react";

import { ApiFailure, askNavigator } from "@/api/client";
import type { Answer, Outside } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { AnswerCard } from "@/components/AnswerCard";
import { Notice } from "@/components/Notice";
import { ScreenTitle } from "@/components/ScreenTitle";
import { TextField } from "@/components/TextField";
import { Button } from "@/components/ui/button";

type State =
  | { name: "idle" }
  | { name: "asking" }
  | { name: "answered"; reply: Answer | Outside }
  | { name: "failed"; why: string };

export function Ask({ waking }: { waking?: (b: boolean) => void }) {
  const { token } = useAuth();
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<State>({ name: "idle" });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setState({ name: "asking" });
    try {
      const reply = await askNavigator(question, token, waking);
      setState({ name: "answered", reply });
    } catch (e) {
      setState({
        name: "failed",
        why:
          e instanceof ApiFailure
            ? e.message
            : "Your question couldn't be asked. Please try again.",
      });
    }
  }

  return (
    <>
      <ScreenTitle title="Ask a question">
        Answers are written from the Rental Housing Act, the Consumer Protection
        Act, the PIE Act and Gauteng&apos;s Unfair Practices Regulations, and
        nothing else.
      </ScreenTitle>

      <form onSubmit={(e) => void submit(e)}>
        <TextField
          label="Your question"
          value={question}
          maxLength={500}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <Button
          type="submit"
          size="lg"
          className="mt-3 h-11 w-full text-sm font-semibold"
          disabled={state.name === "asking"}
        >
          Ask
        </Button>
      </form>

      <div aria-live="polite">
        {state.name === "answered" && "outside" in state.reply ? (
          <section
            aria-labelledby="outside-title"
            className="mt-4 rounded-lg border border-l-4 border-border bg-muted/60 px-4 py-4"
          >
            <h2 id="outside-title" className="text-panel-title text-foreground">
              Outside what Tokelo covers
            </h2>
            <p className="text-body mt-2 text-foreground">
              {state.reply.message}
            </p>
          </section>
        ) : null}
        {state.name === "answered" && !("outside" in state.reply) ? (
          <AnswerCard answer={state.reply} />
        ) : null}
      </div>

      {state.name === "failed" ? (
        <Notice title="Couldn't ask that" tone="destructive" role="alert">
          {state.why}
        </Notice>
      ) : null}
    </>
  );
}
