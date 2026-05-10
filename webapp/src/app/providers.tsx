"use client";

import { ConnectionProvider, WalletProvider, useWallet } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import "@solana/wallet-adapter-react-ui/styles.css";
import { createContext, useContext, ReactNode, useEffect, useMemo, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const RPC_ENDPOINT = process.env.NEXT_PUBLIC_RPC_URL ?? "https://api.devnet.solana.com";

export interface SeekerUser {
  id: string;
  wallet_address: string;
}

// undefined = auth check in progress, null = confirmed not logged in, SeekerUser = logged in
export const UserContext = createContext<SeekerUser | null | undefined>(undefined);
export function useUser() { return useContext(UserContext); }

function encodeBase58(bytes: Uint8Array): string {
  const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  let n = BigInt(0);
  for (const b of bytes) n = n * 256n + BigInt(b);
  let s = "";
  while (n > 0n) { s = ALPHABET[Number(n % 58n)] + s; n /= 58n; }
  for (const b of bytes) { if (b !== 0) break; s = "1" + s; }
  return s;
}

function AuthGate({ children }: { children: ReactNode }) {
  const { publicKey, signMessage, connected } = useWallet();
  const authing = useRef(false);
  // undefined = auth check in progress, null = confirmed no session, SeekerUser = logged in
  const [user, setUser] = useState<SeekerUser | null | undefined>(undefined);

  // Restore session from JWT on mount — no wallet interaction needed
  useEffect(() => {
    const token = localStorage.getItem("seeker_token");
    if (!token) { setUser(null); return; }
    fetch(`${API}/users/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (!r.ok) {
          // Token expired or invalid — clear it
          localStorage.removeItem("seeker_token");
          return null;
        }
        return r.json();
      })
      .then((u) => setUser(u ? { id: u.id, wallet_address: u.wallet_address } : null))
      .catch(() => setUser(null));
  }, []);

  // Sign challenge when wallet connects and no valid session exists
  useEffect(() => {
    if (!connected || !publicKey || !signMessage || authing.current) return;
    if (localStorage.getItem("seeker_token")) return;

    authing.current = true;
    (async () => {
      try {
        const walletAddress = publicKey.toBase58();
        const challengeRes = await fetch(`${API}/users/challenge?wallet_address=${walletAddress}`);
        const { challenge } = await challengeRes.json();
        const sig = await signMessage(new TextEncoder().encode(challenge));
        const loginRes = await fetch(`${API}/users/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ wallet_address: walletAddress, signature: encodeBase58(sig), challenge }),
        });
        const data = await loginRes.json();
        localStorage.setItem("seeker_token", data.access_token);
        setUser({ id: data.user.id, wallet_address: data.user.wallet_address });
      } catch (e) {
        console.error("Wallet auth failed", e);
        setUser(null);
      } finally {
        authing.current = false;
      }
    })();
  }, [connected, publicKey, signMessage]);

  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}

export function Providers({ children }: { children: ReactNode }) {
  const wallets = useMemo(() => [], []);

  return (
    <ConnectionProvider endpoint={RPC_ENDPOINT}>
      <WalletProvider wallets={wallets} autoConnect>
        <WalletModalProvider>
          <AuthGate>{children}</AuthGate>
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
