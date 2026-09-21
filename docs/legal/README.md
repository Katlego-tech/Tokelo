# `docs/legal/` — the curated legal sources

Everything Tokelo says about the law comes from here. A rule in the catalogue may cite only an ID
in `sections/`, and so may a navigator topic; both are refused when they load if they name
anything else (REQ-006). **This directory is therefore the ceiling on what the product can say** —
not a reference shelf, but the whole of the law Tokelo knows.

That is why each file carries more than the words.

## What a curated section looks like

`sections/<id>.md`: TOML front matter between `+++` lines, then the section's own text, verbatim.

```markdown
+++
id = "CPA-48"
act = "Consumer Protection Act 68 of 2008"
section = "48"
title = "Unfair, unreasonable or unjust contract terms"

[source]
publisher = "Government Gazette 32186, Notice 467, 29 April 2009"
url = "https://www.gov.za/sites/default/files/32186_467.pdf"
pages = "24-25"
retrieved = "2026-09-21"
as_at = "2026-09-21"
amendments = "As enacted. The Act was amended by the National Credit Amendment Act 19 of 2014 (in force 13 March 2015); this section's text has been checked against the consolidation of that date."
+++
   48. (1) A supplier must not—
      …
```

- **`id`** is what a rule or a topic cites: `<ACT>-<section>`, e.g. `RHA-4`, `CPA-14`, `PIE-4`,
  `GT-REG-3`. It never changes once a rule uses it.
- **The text is verbatim.** Subsection numbering, punctuation and the em dashes are the Act's.
  Nothing is paraphrased here — paraphrase belongs in a rule's explanation, which cites this.
- **`amendments` and `as_at` are not paperwork.** A tenant may be standing in front of a Tribunal
  with what Tokelo told them. A section with no date is a citation nobody can check, and text "as
  enacted" is not the law if the Act has since been amended.

## Where the text may come from

In order of preference:

1. A **consolidated, point-in-time** text that states which amendments it includes (SAFLII,
   LawLibrary, or a legal publisher).
2. The **official gazette** for the Act as enacted, *plus* every amending Act, consolidated by
   hand and recorded as such.
3. Nothing else. Not a law firm's summary, not a blog, not a model's memory.

South African copyright does not subsist in official texts of a legislative nature (Copyright Act
98 of 1978, section 12(8)(a)), so the sections may be reproduced in full here.

`source/` holds the documents the sections were taken from, so a curated line can be read against
the page it came from.

## How the gazette PDFs are read

The older gazettes are scans. Two things matter:

- **Margin line numbers.** A gazette prints line numbers down the right margin, and they land in
  the middle of sentences when the PDF's text layer is extracted. The text column is cropped off
  at 468 pt (`pdftotext -layout -x 0 -y 0 -W 468 -H 792`) so they never enter the text.
- **A corrupted text layer.** The Rental Housing Act's gov.za PDF is an OCR'd scan whose layer
  reads `bonajde` for *bona fide* and `ri~hts` for *rights*. It must not be used. Where only a
  scan exists, the section is transcribed from the page images and the page range recorded, so
  every line can be checked.

## What is curated, and how current each one is

| Source | Sections | Text from | Currency |
|---|---|---|---|
| Rental Housing Act 50 of 1999 | 4, 5, 13 | SAFLII consolidation (`source/rha1999171.pdf`) | as amended by Act 43 of 2007. **Act 35 of 2014 has never been proclaimed**, so its deletion of s 4(2)–(5) and its insertion of ss 4A and 4B are not here |
| Consumer Protection Act 68 of 2008 | 14, 48 | SAFLII consolidation (`source/cpa2008246.pdf`) | updated to 13 March 2015; neither section carries an amendment note |
| PIE Act 19 of 1998 | 1, 4, 5, 6, 8 | the gazette (`source/pie-a19-98-gazette.pdf`) | **the weakest of the four.** No amending Act was traced, but that is an absence of evidence rather than a consolidation. Bills were tabled in 2005 and 2023; neither was traced as enacted |
| Unfair Practices Regulations, 2001 (Gauteng) | 3, 9, 10, 12, 13 | transcribed from the province's scan (`source/gauteng-unfair-practices-regulations-2001.pdf`) | none traced. **Gauteng only** — a tenant elsewhere has the Acts, not these, and an explanation citing one must say so |

### Before a release shows any of this to a tenant

- **Confirm the PIE Act's currency** against a point-in-time source. It is the one section set here resting on "nothing found" rather than a publisher's consolidation (T052).
- **Check the Rental Housing Amendment Act 35 of 2014 has still not been proclaimed.** The day it commences, ss 4A and 4B become law, this set is wrong, and every rule citing RHA-4 or RHA-5 needs re-reading.
- **Say "Gauteng" wherever a regulation is cited.** The Acts are national; these regulations are not.

Each of those is in the section files' own `amendments` field as well, so the code can show it and no reader has to come here to find out.
