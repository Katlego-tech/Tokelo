// On every screen, under everything (docs/design/web.md §6, "Wording the screens must keep").
// Tokelo explains the law; it does not advise on anyone's case, and a tenant should never have
// to scroll to find that out.
export function LegalNotice() {
  return (
    <p className="mt-10 border-t border-line pt-4 text-[11px] text-muted">
      Legal information, not legal advice · English only
    </p>
  );
}
