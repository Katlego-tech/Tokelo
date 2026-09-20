// Uploading a lease (docs/design/web/upload.svg; REQ-002, REQ-003).
import { ScreenTitle } from "@/components/ScreenTitle";
import { Uploader } from "@/components/Uploader";

export function LeaseNew() {
  return (
    <>
      <ScreenTitle title="Upload a lease">
        We read every page and check its clauses against the law.
      </ScreenTitle>
      <Uploader kind="lease" />
    </>
  );
}
