// Tokelo's mark: a page with a corner turned, and a tick inside it.
//
// The word means "a right" — something a tenant holds, and this is the page that shows it. Drawn
// inline rather than fetched: it is a few hundred bytes, it inherits the colour it sits on, and
// it costs no request (ADR-0010's content security policy allows none from elsewhere anyway).
export function Mark({ className = "size-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      <path
        d="M6 2.75h7.5L19.25 8.5v12.75a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3.75a1 1 0 0 1 1-1Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M13.25 2.75V8.5h5.75" fill="none" stroke="currentColor" strokeWidth="1.6"
        strokeLinejoin="round" />
      <path d="M8.75 14.25l2.25 2.25 4.25-4.5" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
