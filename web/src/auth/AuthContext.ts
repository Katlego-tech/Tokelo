// What a screen may know about who is signed in (docs/design/web.md §4).
//
// The context is this small on purpose: a screen can ask for the tenant's state, sign them in or
// out, and get a token for a call. It cannot reach the tokens themselves, and there is nowhere
// for a screen to keep one.
import { createContext, useContext } from "react";

export type AuthStatus = "loading" | "signed-out" | "confirming" | "signed-in";

export type Auth = {
  status: AuthStatus;
  email: string | null;
  signUp: (email: string, password: string) => Promise<void>;
  confirm: (code: string) => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  token: () => Promise<string>;
};

export const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth outside AuthProvider");
  return auth;
}
