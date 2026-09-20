// Under every screen (docs/design/web.md §6, "Wording the screens must keep"). Tokelo explains
// the law; it does not advise on anyone's case, and a tenant should never have to look for that.
export function LegalNotice() {
  return (
    <p className="mt-5 px-1 text-center text-[11px] text-muted-foreground">
      Legal information, not legal advice · English only
    </p>
  );
}
