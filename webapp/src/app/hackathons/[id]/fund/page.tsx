"use client";
import { use, useEffect, useState } from "react";
import { useWallet, useConnection } from "@solana/wallet-adapter-react";
import { useRouter } from "next/navigation";
import { Transaction } from "@solana/web3.js";
import dynamic from "next/dynamic";

const WalletMultiButton = dynamic(
  async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton,
  { ssr: false }
);

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface HackathonInfo {
  title: string;
  prize_pool_usdc: number;
  status: string;
}

export default function FundEscrowPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: hackathonId } = use(params);
  const { publicKey, signTransaction } = useWallet();
  const { connection } = useConnection();
  const router = useRouter();

  const [hackathon, setHackathon] = useState<HackathonInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [funding, setFunding] = useState(false);
  const [fundingStep, setFundingStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/hackathons/${hackathonId}`)
      .then((r) => r.json())
      .then(setHackathon)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [hackathonId]);

  const fund = async () => {
    if (!publicKey || !hackathon || !signTransaction) return;
    setFunding(true);
    setFundingStep(null);
    setError(null);
    try {
      const token = localStorage.getItem("seeker_token");

      // Fetch a fresh unsigned tx (blockhash expires in ~60s so fetch on click)
      setFundingStep("Building transaction…");
      const txRes = await fetch(`${API}/hackathons/${hackathonId}/create-escrow-tx`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!txRes.ok) throw new Error((await txRes.json()).detail);
      const { transaction_b64, escrow_pda } = await txRes.json();

      const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
      const tx = Transaction.from(txBytes);

      // Guard: wallet connected must match the wallet the transaction was built for.
      // If the JWT is stale (logged in with a different wallet than currently connected),
      // the transaction fee payer won't match and Phantom will reject it with a
      // misleading "simulation failed" message.
      const txFeePayer = tx.feePayer?.toBase58();
      if (txFeePayer && txFeePayer !== publicKey.toBase58()) {
        throw new Error(
          `Wallet mismatch: this hackathon belongs to ${txFeePayer} but you are connected as ${publicKey.toBase58()}. ` +
          `Please log out and reconnect with the correct wallet.`
        );
      }

      // Pre-flight simulation on our devnet connection — surfaces real errors with
      // full program logs before Phantom is ever involved.
      setFundingStep("Simulating transaction…");
      const simResult = await connection.simulateTransaction(tx);
      if (simResult.value.err) {
        const logs = (simResult.value.logs ?? []).join("\n");
        throw new Error(
          `Simulation failed: ${JSON.stringify(simResult.value.err)}\n\nProgram logs:\n${logs}`
        );
      }

      // Phantom signs only — no send. Phantom may still show its own simulation
      // preview, but we've already confirmed validity above. Sending through our
      // own connection (sendRawTransaction) avoids Phantom's RPC for submission.
      setFundingStep("Waiting for wallet approval…");
      const signedTx = await signTransaction(tx);

      setFundingStep("Submitting transaction…");
      const sig = await connection.sendRawTransaction(signedTx.serialize(), {
        skipPreflight: false,
        preflightCommitment: "confirmed",
      });

      setFundingStep("Confirming on-chain…");
      await connection.confirmTransaction(sig, "confirmed");

      // Register escrow with backend → hackathon moves to "open"
      const patchRes = await fetch(`${API}/hackathons/${hackathonId}/escrow`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ escrow_pubkey: escrow_pda, onchain_pda: escrow_pda }),
      });
      if (!patchRes.ok) throw new Error((await patchRes.json()).detail);

      router.push(`/dashboard/${hackathonId}`);
    } catch (e: any) {
      console.error("fund error:", e, "inner:", e?.error);
      const inner = e?.error;
      const detail = inner ? ` — ${inner?.message ?? JSON.stringify(inner)}` : "";
      setError((e?.message ?? "Unknown error") + detail);
    } finally {
      setFunding(false);
      setFundingStep(null);
    }
  };

  const prizeUsdc = hackathon ? hackathon.prize_pool_usdc / 1_000_000 : 0;

  return (
    <div className="max-w-lg mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-2">Fund Escrow</h1>
      <p className="text-gray-500 mb-8">
        Deposit the prize pool on-chain to open your hackathon for project submissions.
        Funds are held in an escrow vault and released only when you verify the winner.
      </p>

      {!publicKey && (
        <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-amber-800 mb-3">Connect your organizer wallet to continue</p>
          <WalletMultiButton />
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm whitespace-pre-wrap font-mono">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : hackathon ? (
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="text-lg font-semibold mb-5">{hackathon.title}</h2>

          <div className="space-y-3 mb-6 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Prize pool to deposit</span>
              <span className="font-semibold text-purple-700">
                ${prizeUsdc.toLocaleString("en-US")} USDC
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Network</span>
              <span className="text-gray-700">Solana Devnet</span>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-xs text-blue-700 mb-6">
            Your wallet will prompt you to sign one transaction that creates the escrow vault and
            transfers {prizeUsdc.toLocaleString("en-US")} USDC. A refund is only available if no
            projects have been submitted.
          </div>

          {hackathon.status !== "draft" ? (
            <div className="text-center py-3 text-green-700 font-medium">
              Escrow already funded — hackathon is {hackathon.status}
            </div>
          ) : (
            <button
              onClick={fund}
              disabled={!publicKey || !signTransaction || funding}
              className="w-full bg-purple-600 text-white py-3 rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {funding && fundingStep ? fundingStep : `Fund $${prizeUsdc.toLocaleString("en-US")} USDC Escrow`}
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
