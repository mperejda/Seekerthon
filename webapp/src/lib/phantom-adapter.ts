import {
  BaseMessageSignerWalletAdapter, WalletName, WalletReadyState,
  WalletConnectionError, WalletNotConnectedError, WalletNotReadyError,
  scopePollingDetectionStrategy,
} from "@solana/wallet-adapter-base";
import { PublicKey, Transaction, VersionedTransaction } from "@solana/web3.js";

interface PhantomProvider {
  isPhantom?: boolean;
  isBackpack?: boolean;
  publicKey: { toBytes(): Uint8Array } | null;
  connect(): Promise<unknown>;
  disconnect(): Promise<void>;
  signMessage(message: Uint8Array): Promise<{ signature: Uint8Array }>;
  signTransaction<T extends Transaction | VersionedTransaction>(transaction: T): Promise<T>;
  on(event: string, listener: (...args: any[]) => void): void;
  removeListener(event: string, listener: (...args: any[]) => void): void;
}

export function getPhantomProvider(): PhantomProvider | undefined {
  if (typeof window === "undefined") return;
  const provider = (window as Window & { phantom?: { solana?: PhantomProvider } }).phantom?.solana;
  // Never use window.solana: another extension can own that shared namespace.
  return provider?.isPhantom && !provider.isBackpack ? provider : undefined;
}

// A distinct adapter name prevents WalletProvider from replacing this adapter
// with an automatically discovered Standard Wallet of the same name.
export const DIRECT_PHANTOM = "Phantom (extension)" as WalletName;

export function preferredWallets<T extends { adapter: { name: string } }>(wallets: T[]): T[] {
  return wallets.filter(({ adapter }) => adapter.name !== "Phantom");
}

export class PhantomAdapter extends BaseMessageSignerWalletAdapter {
  name = DIRECT_PHANTOM;
  url = "https://phantom.app";
  icon = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" rx="8" fill="#ab9ff2"/><text x="16" y="23" text-anchor="middle" font-size="23" fill="white">P</text></svg>');
  supportedTransactionVersions = new Set<"legacy" | 0>(["legacy", 0]);
  publicKey: PublicKey | null = null;
  connecting = false;
  private provider: PhantomProvider | null = null;
  private state = typeof window === "undefined" ? WalletReadyState.Unsupported : WalletReadyState.NotDetected;

  constructor() {
    super();
    scopePollingDetectionStrategy(() => {
      if (!getPhantomProvider()) return false;
      this.state = WalletReadyState.Installed;
      this.emit("readyStateChange", this.state);
      return true;
    });
  }

  get readyState() { return this.state; }

  async connect() {
    if (this.connected || this.connecting) return;
    const provider = getPhantomProvider();
    if (!provider) throw new WalletNotReadyError("Phantom is not available. Open or install Phantom and try again.");
    this.connecting = true;
    try {
      await provider.connect();
      if (!provider.publicKey) throw new Error("Phantom did not return an account.");
      this.provider = provider;
      this.publicKey = new PublicKey(provider.publicKey.toBytes());
      provider.on("disconnect", this.disconnected);
      provider.on("accountChanged", this.accountChanged);
      this.emit("connect", this.publicKey);
    } catch (error) {
      const wrapped = new WalletConnectionError(error instanceof Error ? error.message : "Phantom connection failed");
      this.emit("error", wrapped);
      throw wrapped;
    } finally {
      this.connecting = false;
    }
  }

  private disconnected = () => {
    this.provider?.removeListener("disconnect", this.disconnected);
    this.provider?.removeListener("accountChanged", this.accountChanged);
    this.provider = null;
    this.publicKey = null;
    this.emit("disconnect");
  };

  private accountChanged = (key: { toBytes(): Uint8Array } | null) => {
    if (!key) { this.disconnected(); return; }
    this.publicKey = new PublicKey(key.toBytes());
    this.emit("connect", this.publicKey);
  };

  async disconnect() {
    const provider = this.provider;
    this.disconnected();
    await provider?.disconnect();
  }

  async signMessage(message: Uint8Array) {
    if (!this.provider || !this.publicKey) throw new WalletNotConnectedError();
    return (await this.provider.signMessage(message)).signature;
  }

  async signTransaction<T extends Transaction | VersionedTransaction>(transaction: T): Promise<T> {
    if (!this.provider || !this.publicKey) throw new WalletNotConnectedError();
    return this.provider.signTransaction(transaction);
  }
}
