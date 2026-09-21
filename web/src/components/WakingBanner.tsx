// Shown while the API is answering 503 and the client is waiting (NFR-002, api.md §4). It says
// what is happening, so a slow first request reads as a wait and not as a broken app.
export function WakingBanner({ waking }: { waking: boolean }) {
  if (!waking) return null;
  return (
    <p
      role="status"
      className="text-note mt-4 rounded-lg border border-primary bg-card px-3 py-2.5
        font-bold text-primary"
    >
      Still waking up: a few seconds
    </p>
  );
}
