"use client";

import { ConnectionProvider, WalletProvider, useWallet } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import "@solana/wallet-adapter-react-ui/styles.css";
import { createContext, useContext, ReactNode, useEffect, useMemo, useState } from "react";

import { authenticateWallet } from "../lib/wallet-auth";
const RPC_ENDPOINT = process.env.NEXT_PUBLIC_RPC_URL ?? "/api/rpc";
const SSR_ORIGIN = "http://localhost:3000";

export interface SeekerUser {
  id: string;
  wallet_address: string;
}

// undefined = signing in, null = no session for the connected wallet.
export const UserContext = createContext<SeekerUser | null | undefined>(undefined);
export function useUser() { return useContext(UserContext); }
const AuthContext = createContext({ error: null as string | null, retry: () => {} });
export function useWalletAuth() { return useContext(AuthContext); }

function AuthGate({ children }: { children: ReactNode }) {
  const { publicKey, signMessage, connected } = useWallet();
  const walletAddress = connected ? publicKey?.toBase58() : undefined;
  const [user, setUser] = useState<SeekerUser | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setUser(walletAddress ? undefined : null);
    if (!walletAddress) return;

    (async () => {
      try {
        const session = await authenticateWallet(walletAddress, signMessage, () => cancelled);
        if (!cancelled && session) setUser({ id: session.id, wallet_address: walletAddress });
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Wallet sign-in failed. Please try again.");
        setUser(null);
      }
    })();

    // Ignore signatures and responses from a disconnected or previous account.
    return () => { cancelled = true; };
  }, [walletAddress, signMessage, attempt]);

  const currentUser = !walletAddress ? null : user && user.wallet_address !== walletAddress ? undefined : user;
  return (
    <AuthContext.Provider value={{ error, retry: () => setAttempt((n) => n + 1) }}>
      <UserContext.Provider value={currentUser}>{children}</UserContext.Provider>
    </AuthContext.Provider>
  );
}

export function Providers({ children }: { children: ReactNode }) {
  // Wallet Standard adapters discover installed wallets automatically.
  const wallets = useMemo(() => [], []);
  const rpcEndpoint = useMemo(() => {
    if (RPC_ENDPOINT.startsWith("http://") || RPC_ENDPOINT.startsWith("https://")) return RPC_ENDPOINT;
    const origin = typeof window === "undefined" ? SSR_ORIGIN : window.location.origin;
    return new URL(RPC_ENDPOINT, origin).toString();
  }, []);

  return (
    <ConnectionProvider endpoint={rpcEndpoint}>
      <WalletProvider wallets={wallets} autoConnect>
        <WalletModalProvider><AuthGate>{children}</AuthGate></WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
