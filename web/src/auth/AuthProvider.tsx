// Cognito, through Amplify's Auth module (docs/design/web.md §2, §4, §8).
//
// Tokens live in **sessionStorage**: they go when the tab does. localStorage would outlive the
// tab on a shared or borrowed phone, which is the device this is built for.
//
// The pool and client come from /config.json at run time, not from the build, so one image
// serves staging and production (ADR-0010).
import {
  confirmSignUp,
  fetchAuthSession,
  signIn as amplifySignIn,
  signOut as amplifySignOut,
  signUp as amplifySignUp,
} from "aws-amplify/auth";
import { Amplify } from "aws-amplify";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { defaultStorage, sessionStorage } from "aws-amplify/utils";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { Config } from "../api/types";
import { AuthContext, type Auth, type AuthStatus } from "./AuthContext";

export function configure(config: Config): void {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.user_pool_id,
        userPoolClientId: config.client_id,
        signUpVerificationMethod: "code",
      },
    },
  });
  cognitoUserPoolsTokenProvider.setKeyValueStorage(
    sessionStorage ?? defaultStorage,
  );
}

export function AuthProvider({
  config,
  children,
}: {
  config: Config;
  children: ReactNode;
}) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [email, setEmail] = useState<string | null>(null);
  const [pending, setPending] = useState<{
    email: string;
    password: string;
  } | null>(null);

  useEffect(() => {
    configure(config);
    // A refresh inside the same tab shouldn't ask a tenant to sign in again.
    fetchAuthSession()
      .then((session) => {
        setStatus(session.tokens?.accessToken ? "signed-in" : "signed-out");
      })
      .catch(() => setStatus("signed-out"));
  }, [config]);

  const signIn = useCallback(async (address: string, password: string) => {
    await amplifySignIn({ username: address, password });
    setEmail(address);
    setStatus("signed-in");
  }, []);

  const signUp = useCallback(async (address: string, password: string) => {
    await amplifySignUp({
      username: address,
      password,
      options: { userAttributes: { email: address } },
    });
    setPending({ email: address, password });
    setEmail(address);
    setStatus("confirming");
  }, []);

  const confirm = useCallback(
    async (code: string) => {
      if (!pending) throw new Error("There is no account waiting for a code.");
      await confirmSignUp({ username: pending.email, confirmationCode: code });
      await signIn(pending.email, pending.password);
      setPending(null);
    },
    [pending, signIn],
  );

  const signOut = useCallback(async () => {
    await amplifySignOut();
    setPending(null);
    setEmail(null);
    setStatus("signed-out");
  }, []);

  const token = useCallback(async () => {
    const session = await fetchAuthSession();
    const accessToken = session.tokens?.accessToken?.toString();
    if (!accessToken) throw new Error("Sign in to use this.");
    return accessToken;
  }, []);

  const auth: Auth = useMemo(
    () => ({ status, email, signUp, confirm, signIn, signOut, token }),
    [status, email, signUp, confirm, signIn, signOut, token],
  );

  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}
