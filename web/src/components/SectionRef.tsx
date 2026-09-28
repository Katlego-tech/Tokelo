// What a flag or an answer rests on, in full: a tenant can look it up, which is the whole point
// of citing it (REQ-006; docs/design/web.md §6's tree, shared by ClauseCard and AnswerCard).
import type { SectionRef as Ref } from "@/api/types";

export function SectionRef({ section }: { section: Ref }) {
  return (
    <span className="block rounded-md border border-border bg-muted/50 px-2.5 py-1.5">
      <span className="text-caption block font-medium text-foreground">
        Section {section.section} · {section.title}
      </span>
      <span className="text-caption block text-muted-foreground">
        {section.act}
      </span>
    </span>
  );
}
