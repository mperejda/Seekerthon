"use client";

import { ConnectionProvider, WalletProvider, useWallet } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import "@solana/wallet-adapter-react-ui/styles.css";
import { ReactNode, useEffect, useMemo, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const RPC_ENDPOINT = process.env.NEXT_PUBLIC_RPC_URL ?? "https://api.devnet.solana.com";

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
  const { publicKey, signMessage, connected, disconnecting } = useWallet();
  const authing = useRef(false);

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
        const { access_token } = await loginRes.json();
        localStorage.setItem("seeker_token", access_token);
      } catch (e) {
        console.error("Wallet auth failed", e);
      } finally {
        authing.current = false;
      }
    })();
  }, [connected, publicKey, signMessage]);

  useEffect(() => {
    if (disconnecting) localStorage.removeItem("seeker_token");
  }, [disconnecting]);

  return <>{children}</>;
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
