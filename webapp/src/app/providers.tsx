"use client";

import { ConnectionProvider, WalletProvider, useWallet } from "@solana/wallet-adapter-react";
import { WalletModalProvider, useWalletModal } from "@solana/wallet-adapter-react-ui";
import "@solana/wallet-adapter-react-ui/styles.css";
import { createContext, useContext, ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { authenticateWallet, restoreWalletSession, selectedWalletSigner } from "../lib/wallet-auth";
const RPC_ENDPOINT = process.env.NEXT_PUBLIC_RPC_URL ?? "/api/rpc";
const SSR_ORIGIN = "http://localhost:3000";

export interface SeekerUser {
  id: string;
  wallet_address: string;
}

// undefined = signing in, null = no session for the connected wallet.
export const UserContext = createContext<SeekerUser | null | undefined>(undefined);
export function useUser() { return useContext(UserContext); }
const AuthContext = createContext({
  error: null as string | null,
  signing: false,
  signIn: () => {},
});
export function useWalletAuth() { return useContext(AuthContext); }

export function WalletSignInNotice() {
  const { wallet, connected, publicKey } = useWallet();
  const { setVisible } = useWalletModal();
  const { error, signing, signIn } = useWalletAuth();
  const user = useUser();
  if (!connected || !wallet || !publicKey || user?.wallet_address === publicKey.toBase58()) return null;
  const name = wallet.adapter.name;
  return (
    <div className="max-w-4xl mx-auto mt-4 px-4">
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900" role="status">
        <p>
          {signing
            ? `Approve the sign-in request in ${name}.`
            : user === undefined
            ? `Checking your ${name} session…`
            : `Connected to ${name}. Sign in to continue.`}
        </p>
        {error && <p className="mt-2 text-red-800">{error}</p>}
        <div className="mt-3 flex gap-4">
          <button type="button" disabled={user === undefined || signing} onClick={signIn}
            className="font-medium underline disabled:opacity-50">
            {error ? `Retry sign-in with ${name}` : `Sign in with ${name}`}
          </button>
          <button type="button" onClick={() => setVisible(true)} className="font-medium underline">
            Change wallet
          </button>
        </div>
      </div>
    </div>
  );
}

function AuthGate({ children }: { children: ReactNode }) {
  const { publicKey, wallet, connected } = useWallet();
  const adapter = wallet?.adapter;
  // Adapter selection can update before WalletProvider's account state does.
  const walletAddress = connected && adapter?.connected &&
    adapter.publicKey?.toBase58() === publicKey?.toBase58() ? publicKey?.toBase58() : undefined;
  const selection = useMemo(() => ({ adapter, walletAddress }), [adapter, walletAddress]);
  const latestSelection = useRef(selection);
  latestSelection.current = selection;
  const generation = useRef(0);
  const pendingSignIn = useRef<number | null>(null);
  const [user, setUser] = useState<SeekerUser | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    const request = ++generation.current;
    pendingSignIn.current = null;
    setSigning(false);
    setError(null);
    setUser(walletAddress ? undefined : null);
    if (walletAddress) {
      // Auto-reconnection may restore a cookie, but must never open a signing
      // prompt for a remembered wallet before the user chooses one.
      restoreWalletSession(walletAddress).then((session) => {
        if (generation.current === request && latestSelection.current === selection) {
          setUser(session ? { id: session.id, wallet_address: walletAddress } : null);
        }
      });
    }
    return () => { generation.current++; };
  }, [selection, walletAddress]);

  const signIn = async () => {
    if (!adapter || !walletAddress || pendingSignIn.current !== null) return;
    const request = ++generation.current;
    pendingSignIn.current = request;
    const isCancelled = () => generation.current !== request || latestSelection.current !== selection;
    setSigning(true);
    setUser(undefined);
    setError(null);
    try {
      const signer = selectedWalletSigner(adapter, walletAddress, () => !isCancelled());
      const session = await authenticateWallet(walletAddress, signer, isCancelled);
      if (!isCancelled() && session) setUser({ id: session.id, wallet_address: walletAddress });
    } catch (err) {
      if (!isCancelled()) {
        setError(err instanceof Error ? err.message : "Wallet sign-in failed. Please try again.");
        setUser(null);
      }
    } finally {
      if (pendingSignIn.current === request) pendingSignIn.current = null;
      if (!isCancelled()) setSigning(false);
    }
  };

  const currentUser = !walletAddress ? null : user && user.wallet_address !== walletAddress ? undefined : user;
  return (
    <AuthContext.Provider value={{ error, signing, signIn }}>
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
