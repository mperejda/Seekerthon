"use client";

import { ConnectionProvider, WalletProvider, WalletContext, useWallet } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import "@solana/wallet-adapter-react-ui/styles.css";
import { createContext, useContext, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { authenticateWallet, selectedWalletSigner } from "../lib/wallet-auth";
import { PhantomAdapter, preferredWallets } from "../lib/phantom-adapter";

const RPC_ENDPOINT = process.env.NEXT_PUBLIC_RPC_URL ?? "/api/rpc";
const SSR_ORIGIN = "http://localhost:3000";

export interface SeekerUser {
  id: string;
  wallet_address: string;
}

// undefined = signing in, null = no session for the connected wallet.
export const UserContext = createContext<SeekerUser | null | undefined>(undefined);
export function useUser() { return useContext(UserContext); }

function AuthGate({ children }: { children: ReactNode }) {
  const { publicKey, wallet, connected } = useWallet();
  const adapter = wallet?.adapter;
  const walletAddress = connected && adapter?.connected &&
    adapter.publicKey?.toBase58() === publicKey?.toBase58() ? publicKey?.toBase58() : undefined;
  const selection = useMemo(() => ({ adapter, walletAddress }), [adapter, walletAddress]);
  const latestSelection = useRef(selection);
  latestSelection.current = selection;
  const [user, setUser] = useState<SeekerUser | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const isCancelled = () => cancelled || latestSelection.current !== selection;
    setError(null);
    setUser(walletAddress ? undefined : null);
    if (!adapter || !walletAddress) return;
    (async () => {
      try {
        const signer = selectedWalletSigner(adapter, walletAddress, () => !isCancelled());
        const session = await authenticateWallet(walletAddress, signer, isCancelled);
        if (!isCancelled() && session) setUser({ id: session.id, wallet_address: walletAddress });
      } catch (err) {
        if (!isCancelled()) {
          setError(err instanceof Error ? err.message : "Wallet sign-in failed.");
          setUser(null);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [adapter, selection, walletAddress]);

  const currentUser = !walletAddress ? null : user && user.wallet_address !== walletAddress ? undefined : user;
  return (
    <UserContext.Provider value={currentUser}>
      {walletAddress && (error || currentUser === undefined) && (
        <div role="status" className="mx-auto max-w-4xl px-4 py-3 text-sm">
          {error
            ? `${error} Use the wallet button to disconnect and reconnect to try again.`
            : `Signing in with ${adapter?.name} — approve the request in that wallet.`}
        </div>
      )}
      {children}
    </UserContext.Provider>
  );
}

function WalletChoices({ children }: { children: ReactNode }) {
  const context = useWallet();
  const wallets = useMemo(() => preferredWallets(context.wallets), [context.wallets]);
  // Keep the original wallet button/modal. Only replace the ambiguous Phantom
  // discovery entry; Backpack and all other Wallet Standard wallets remain.
  return <WalletContext.Provider value={{ ...context, wallets }}>{children}</WalletContext.Provider>;
}

export function Providers({ children }: { children: ReactNode }) {
  const wallets = useMemo(() => [new PhantomAdapter()], []);
  const rpcEndpoint = useMemo(() => {
    if (RPC_ENDPOINT.startsWith("http://") || RPC_ENDPOINT.startsWith("https://")) return RPC_ENDPOINT;
    const origin = typeof window === "undefined" ? SSR_ORIGIN : window.location.origin;
    return new URL(RPC_ENDPOINT, origin).toString();
  }, []);

  return (
    <ConnectionProvider endpoint={rpcEndpoint}>
      <WalletProvider wallets={wallets} autoConnect localStorageKey="seekerthon.wallet.v2">
        <WalletChoices>
          <WalletModalProvider><AuthGate>{children}</AuthGate></WalletModalProvider>
        </WalletChoices>
      </WalletProvider>
    </ConnectionProvider>
  );
}
