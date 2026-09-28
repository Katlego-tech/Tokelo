// A navigator answer (docs/design/web/navigator.svg; REQ-014, REQ-006).
//
// The topic's written answer, set as the plain paragraphs and lists it was written in: React
// escapes every word, and nothing is ever rendered as HTML (web.md § Threats). Then the curated
// sections it rests on, and the notice, as the API sent them.
import { ScaleIcon } from "lucide-react";

import type { Answer } from "@/api/types";
import { SectionRef } from "@/components/SectionRef";
import { Card, CardContent } from "@/components/ui/card";

/** The answer's blocks: a paragraph, or a run of "- " lines as a list. */
function blocks(text: string): Array<{ list: boolean; lines: string[] }> {
  return text.split(/\n\s*\n/).flatMap((block) => {
    const out: Array<{ list: boolean; lines: string[] }> = [];
    for (const line of block.split("\n")) {
      const item = line.startsWith("- ");
      const last = out[out.length - 1];
      if (last && last.list === item)
        last.lines.push(item ? line.slice(2) : line);
      else out.push({ list: item, lines: [item ? line.slice(2) : line] });
    }
    return out;
  });
}

export function AnswerCard({ answer }: { answer: Answer }) {
  return (
    <Card className="mt-4 gap-0 border-l-4 border-l-primary bg-muted/60 py-0 shadow-none">
      <CardContent className="px-4 py-4">
        <h2 className="text-panel-title text-foreground">{answer.topic}</h2>
        <div className="text-body mt-2 space-y-2 text-foreground">
          {blocks(answer.answer).map((block, n) =>
            block.list ? (
              <ul key={n} className="list-disc space-y-1 pl-5">
                {block.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : (
              <p key={n}>{block.lines.join(" ")}</p>
            ),
          )}
        </div>
        <ul
          className="mt-3 flex flex-wrap gap-2"
          aria-label="The law this rests on"
        >
          {answer.sections.map((section) => (
            <li key={section.id}>
              <SectionRef section={section} />
            </li>
          ))}
        </ul>
        <p className="text-note mt-3 flex gap-2 text-muted-foreground">
          <ScaleIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{answer.notice}</span>
        </p>
      </CardContent>
    </Card>
  );
}
