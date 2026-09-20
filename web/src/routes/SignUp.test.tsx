// Creating an account (T027; docs/design/web.md §4, §6, docs/design/web/sign-up.svg).
// [REQ-015] [REQ-001] [NFR-009]
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Auth } from "../auth/AuthContext";
import { axeClean } from "../test/axe";
import { renderRoute } from "../test/render";

const auth: Auth = {
  status: "signed-out",
  email: null,
  signUp: vi.fn(async () => {}),
  confirm: vi.fn(async () => {}),
  signIn: vi.fn(async () => {}),
  signOut: vi.fn(async () => {}),
  token: vi.fn(async () => ""),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("[REQ-015] the privacy notice comes before the account", () => {
  it("says where the documents are kept, and under which law they leave the country", async () => {
    renderRoute("/sign-up", { auth });
    const notice = screen.getByRole("region", { name: /privacy notice/i });
    expect(notice).toHaveTextContent(/Ireland/i);
    expect(notice).toHaveTextContent(/POPIA section 72/i);
    expect(notice).toHaveTextContent(/delete everything/i);
  });

  it("keeps Create account out of reach until the tenant says they have read it", async () => {
    const user = userEvent.setup();
    renderRoute("/sign-up", { auth });

    const create = screen.getByRole("button", { name: /create account/i });
    expect(create).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /i have read the privacy notice/i }));
    expect(create).toBeEnabled();
  });
});

describe("[REQ-001] signing up", () => {
  it("takes the email and password to Cognito, then asks for the emailed code", async () => {
    const user = userEvent.setup();
    renderRoute("/sign-up", { auth });

    await user.click(screen.getByRole("checkbox", { name: /i have read the privacy notice/i }));
    await user.type(screen.getByLabelText(/email/i), "tenant@example.com");
    await user.type(screen.getByLabelText(/password/i), "hunter2-hunter2");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(auth.signUp).toHaveBeenCalledWith("tenant@example.com", "hunter2-hunter2");
    expect(await screen.findByLabelText(/code/i)).toBeInTheDocument();
  });

  it("shows what Cognito refused, in Cognito's own words", async () => {
    const user = userEvent.setup();
    const refusing: Auth = {
      ...auth,
      signUp: vi.fn(async () => {
        throw new Error("Password did not conform with policy: Password not long enough");
      }),
    };
    renderRoute("/sign-up", { auth: refusing });

    await user.click(screen.getByRole("checkbox", { name: /i have read the privacy notice/i }));
    await user.type(screen.getByLabelText(/email/i), "tenant@example.com");
    await user.type(screen.getByLabelText(/password/i), "short");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/not long enough/i);
  });
});

describe("[NFR-009] accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = renderRoute("/sign-up", { auth });
    await axeClean(container);
  });

  it("has no axe violations on the sign-in screen either", async () => {
    const { container } = renderRoute("/sign-in", { auth });
    await axeClean(container);
  });
});

describe("the legal notice", () => {
  it("is on every screen, because the app is information and not advice", () => {
    renderRoute("/sign-in", { auth });
    expect(screen.getByText(/legal information, not legal advice/i)).toBeInTheDocument();
  });
});
