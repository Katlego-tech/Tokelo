// The tenant's account (docs/design/web/account.svg; T048; REQ-015, REQ-016): who is signed in,
// the privacy notice, signing out, and deleting everything.
import { useAuth } from "@/auth/AuthContext";
import { DeleteAccount } from "@/components/DeleteAccount";
import { PrivacyNotice } from "@/components/PrivacyNotice";
import { ScreenTitle } from "@/components/ScreenTitle";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export function Account({ waking }: { waking?: (b: boolean) => void }) {
  const { email, signOut } = useAuth();
  return (
    <>
      <ScreenTitle title="Your account">Signed in as {email}</ScreenTitle>
      <PrivacyNotice />
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="mt-4 h-11 w-full text-sm font-semibold"
        onClick={() => void signOut()}
      >
        Sign out
      </Button>
      <Separator className="mt-6" />
      <DeleteAccount waking={waking} />
    </>
  );
}
