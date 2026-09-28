// The account screen, and deleting everything (T048; docs/design/web/account.svg, api.md §4
// "Deleting an account"). [REQ-016] [REQ-015] [NFR-009]
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Auth } from "../auth/AuthContext";
import { axeClean } from "../test/axe";
import { renderRoute } from "../test/render";

function signedIn(): Auth {
  return {
    status: "signed-in",
    email: "tenant@example.com",
    signUp: vi.fn(async () => {}),
    confirm: vi.fn(async () => {}),
    signIn: vi.fn(async () => {}),
    signOut: vi.fn(async () => {}),
    deleteAccount: vi.fn(async () => {}),
    token: vi.fn(async () => "a-token"),
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function answers(...responses: Response[]) {
  const fetch = vi.fn();
  for (const response of responses) fetch.mockResolvedValueOnce(response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const CONFIRM = "Type DELETE to confirm";

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the account", () => {
  it("says who is signed in, keeps the privacy notice to hand, and signs out", async () => {
    const auth = signedIn();
    renderRoute("/account", { auth });

    expect(screen.getByText("Signed in as tenant@example.com")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Privacy notice" })).toBeTruthy();
    // The header has its own; this is the account screen's, below the notice.
    const buttons = screen.getAllByRole("button", { name: "Sign out" });
    await userEvent.click(buttons[buttons.length - 1]);
    expect(auth.signOut).toHaveBeenCalled();
  });
});

describe("[REQ-016] deleting everything", () => {
  it("says what goes, and what the audit log keeps, before anything is deleted", () => {
    renderRoute("/account", { auth: signedIn() });

    expect(
      screen.getByText(/Deletes your files, leases, evidence and dossiers/),
    ).toBeTruthy();
    expect(screen.getByText(/without your identity/)).toBeTruthy();
    expect(screen.getByText(/can't be undone/)).toBeTruthy();
  });

  it("stays disabled until DELETE is typed, exactly (web.md § Threats)", async () => {
    renderRoute("/account", { auth: signedIn() });
    const button = screen.getByRole("button", { name: "Delete my account" });

    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText(CONFIRM), "delete");
    expect(button).toBeDisabled();
    await userEvent.clear(screen.getByLabelText(CONFIRM));
    await userEvent.type(screen.getByLabelText(CONFIRM), "DELETE");
    expect(button).toBeEnabled();
  });

  it("deletes the files and records, then the sign-in, and says it's done", async () => {
    const auth = signedIn();
    const fetch = answers(json({}, 202));
    renderRoute("/account", { auth });

    await userEvent.type(screen.getByLabelText(CONFIRM), "DELETE");
    await userEvent.click(
      screen.getByRole("button", { name: "Delete my account" }),
    );

    expect(await screen.findByText("Your account is deleted")).toBeTruthy();
    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe("/api/account");
    expect(init.method).toBe("DELETE");
    expect(auth.deleteAccount).toHaveBeenCalledOnce();
  });

  it("leaves the sign-in alone when the files and records couldn't be deleted", async () => {
    const auth = signedIn();
    answers(
      json(
        { error: { code: "failed", message: "Something went wrong." } },
        500,
      ),
    );
    renderRoute("/account", { auth });

    await userEvent.type(screen.getByLabelText(CONFIRM), "DELETE");
    await userEvent.click(
      screen.getByRole("button", { name: "Delete my account" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong.",
    );
    expect(auth.deleteAccount).not.toHaveBeenCalled();
  });

  it("says so when everything went but the sign-in couldn't be removed", async () => {
    const auth = signedIn();
    auth.deleteAccount = vi.fn(async () => {
      throw new Error("Network error");
    });
    answers(json({}, 202));
    renderRoute("/account", { auth });

    await userEvent.type(screen.getByLabelText(CONFIRM), "DELETE");
    await userEvent.click(
      screen.getByRole("button", { name: "Delete my account" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your files and records are deleted, but your sign-in couldn't be removed",
    );
  });
});

describe("[NFR-009] accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = renderRoute("/account", { auth: signedIn() });
    await axeClean(container);
  });
});
