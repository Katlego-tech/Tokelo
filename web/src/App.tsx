// The app shell (docs/design/web.md §6). Its screens come with T027 onwards; each builds from its
// reference image in docs/design/web/.
export function App() {
  return (
    <main className="mx-auto max-w-md p-5">
      <h1 className="text-2xl font-bold text-slate-900">Tokelo</h1>
      <p className="mt-2 text-sm text-slate-700">Legal information, not legal advice.</p>
    </main>
  );
}
