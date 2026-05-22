"use client";
import { useState, useEffect } from "react";
import { useWallet, useConnection } from "@solana/wallet-adapter-react";
import { Transaction } from "@solana/web3.js";
import dynamic from "next/dynamic";

const WalletMultiButton = dynamic(
  async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton,
  { ssr: false }
);

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const ACTIVE_STATUSES = new Set(["open", "voting", "verifying"]);

export default function CreateHackathonPage() {
  const { publicKey, signTransaction } = useWallet();
  const { connection } = useConnection();
  const [form, setForm] = useState({
    title: "",
    description: "",
    prize_usdc: "",
    voting_start: "",
    voting_end: "",
  });
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeHackathon, setActiveHackathon] = useState<{ title: string } | null>(null);
  const [created, setCreated] = useState<{ id: string; title: string; prizeUsdc: number } | null>(null);

  useEffect(() => {
    fetch(`${API}/hackathons/`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: { status: string; title: string }[]) => {
        const active = list.find((h) => ACTIVE_STATUSES.has(h.status));
        if (active) setActiveHackathon(active);
      })
      .catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!publicKey || !signTransaction) return;
    setLoading(true);
    setError(null);

    try {
      setStep("Creating hackathon…");
      const createRes = await fetch(`${API}/hackathons/`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: form.title,
          description: form.description,
          prize_pool_usdc: Math.round(parseFloat(form.prize_usdc) * 1_000_000),
          voting_start: new Date(form.voting_start).toISOString(),
          voting_end: new Date(form.voting_end).toISOString(),
        }),
      });
      if (!createRes.ok) throw new Error((await createRes.json()).detail);
      const hackathon = await createRes.json();

      setStep("Building transaction…");
      const txRes = await fetch(`${API}/hackathons/${hackathon.id}/create-escrow-tx`, {
        credentials: "include",
      });
      if (!txRes.ok) throw new Error((await txRes.json()).detail);
      const { transaction_b64, escrow_pda } = await txRes.json();

      const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
      const tx = Transaction.from(txBytes);

      const txFeePayer = tx.feePayer?.toBase58();
      if (txFeePayer && txFeePayer !== publicKey.toBase58()) {
        throw new Error(
          `Wallet mismatch: transaction was built for ${txFeePayer} but you are connected as ${publicKey.toBase58()}. ` +
            `Please log out and reconnect with the correct wallet.`
        );
      }

      setStep("Simulating transaction…");
      const simResult = await connection.simulateTransaction(tx);
      if (simResult.value.err) {
        const errStr = JSON.stringify(simResult.value.err);
        if (!errStr.includes("BlockhashNotFound")) {
          const logs = (simResult.value.logs ?? []).join("\n");
          throw new Error(`Simulation failed: ${errStr}\n\nProgram logs:\n${logs}`);
        }
      }

      setStep("Waiting for wallet approval…");
      const signedTx = await signTransaction(tx);

      setStep("Submitting transaction…");
      const sig = await connection.sendRawTransaction(signedTx.serialize(), {
        skipPreflight: false,
        preflightCommitment: "confirmed",
      });

      setStep("Confirming on-chain…");
      await connection.confirmTransaction(sig, "confirmed");

      setStep("Opening hackathon…");
      const patchRes = await fetch(`${API}/hackathons/${hackathon.id}/escrow`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ escrow_pubkey: escrow_pda, onchain_pda: escrow_pda }),
      });
      if (!patchRes.ok) throw new Error((await patchRes.json()).detail);

      setCreated({
        id: hackathon.id,
        title: form.title,
        prizeUsdc: Math.round(parseFloat(form.prize_usdc)),
      });
    } catch (err: any) {
      console.error("create hackathon error:", err);
      const inner = err?.error;
      const detail = inner ? ` — ${inner?.message ?? JSON.stringify(inner)}` : "";
      setError((err?.message ?? "Unknown error") + detail);
    } finally {
      setLoading(false);
      setStep(null);
    }
  };

  const prizeUsdc = parseFloat(form.prize_usdc) || 0;

  if (created) {
    const xText = `I just launched ${created.title} on Seekerthon with a prize of $${created.prizeUsdc.toLocaleString("en-US")} USDC! Register to submit your projects at seekerthon.com`;
    const xUrl = `https://x.com/intent/tweet?${new URLSearchParams({ text: xText }).toString()}`;
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <div className="text-5xl mb-4">🎉</div>
        <h2 className="text-2xl font-bold mb-2">Hackathon launched!</h2>
        <p className="text-gray-600 mb-8">
          Your hackathon is live and accepting submissions. Let the community know!
        </p>
        <div className="flex flex-col items-center gap-4">
          <a
            href={xUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-black px-5 py-2.5 text-sm font-medium text-white hover:bg-gray-800"
          >
            <span className="font-bold">X</span>
            <span>Post on X</span>
          </a>
          <a href={`/dashboard/${created.id}`} className="text-purple-600 hover:underline text-sm">
            Go to dashboard →
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-8">Create Hackathon</h1>

      {activeHackathon && (
        <div className="mb-8 p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-800">
          <p className="font-medium">A hackathon is currently ongoing</p>
          <p className="text-sm mt-1">
            <span className="font-semibold">{activeHackathon.title}</span> must finish before a new one can be created.
          </p>
        </div>
      )}

      {!publicKey && (
        <div className="mb-8 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-amber-800 mb-3">Connect your organizer wallet to continue</p>
          <WalletMultiButton />
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm whitespace-pre-wrap font-mono">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm font-medium mb-1">Title</label>
          <input
            type="text"
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Description</label>
          <textarea
            required
            rows={4}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Prize pool (USDC)</label>
          <input
            type="number"
            required
            min="1"
            step="1"
            value={form.prize_usdc}
            onChange={(e) => setForm({ ...form, prize_usdc: e.target.value })}
            className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
          <p className="text-xs text-gray-500 mt-1">Launch hackathons are limited to 100 project submissions.</p>
          <p className="text-xs text-amber-700 mt-2">
            Seekerthon has not been audited yet. We are actively raising funds for a security audit.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Voting starts</label>
            <input
              type="datetime-local"
              required
              value={form.voting_start}
              onChange={(e) => setForm({ ...form, voting_start: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Voting ends</label>
            <input
              type="datetime-local"
              required
              value={form.voting_end}
              onChange={(e) => setForm({ ...form, voting_end: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
        </div>

        {prizeUsdc > 0 && (
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-xs text-blue-700">
            Your wallet will prompt you to sign one transaction that creates the escrow vault and transfers{" "}
            {prizeUsdc.toLocaleString("en-US")} USDC. A refund is only available if no projects have been submitted.
          </div>
        )}

        <button
          type="submit"
          disabled={!publicKey || !signTransaction || loading || !!activeHackathon}
          className="w-full bg-purple-600 text-white py-3 rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading && step
            ? step
            : prizeUsdc > 0
            ? `Create & Fund $${prizeUsdc.toLocaleString("en-US")} USDC Escrow`
            : "Create Hackathon"}
        </button>
      </form>
    </div>
  );
}
