// Uploading a lease (docs/design/web/upload.svg; REQ-002, REQ-003).
import { Uploader } from "../components/Uploader";

export function LeaseNew() {
  return (
    <>
      <h1 className="mt-6 text-[22px] font-bold text-ink">Upload a lease</h1>
      <Uploader kind="lease" />
    </>
  );
}
