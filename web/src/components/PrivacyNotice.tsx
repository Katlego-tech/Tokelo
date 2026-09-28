// The privacy notice (REQ-015): the same words at sign-up, where it must be read before an
// account exists, and on the account screen, where it stays to hand.
import { Notice } from "@/components/Notice";

export function PrivacyNotice() {
  return (
    <Notice title="Privacy notice">
      Your documents are stored by AWS in Ireland (EU), which takes them out of
      South Africa under POPIA section 72. Only you can see them, and you can
      delete everything at any time.
    </Notice>
  );
}
