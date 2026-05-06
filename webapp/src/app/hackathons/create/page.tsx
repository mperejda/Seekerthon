"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useWallet } from "@solana/wallet-adapter-react";
import dynamic from "next/dynamic";
const WalletMultiButton = dynamic(
  async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton,
  { ssr: false }
);

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export default function CreateHackathonPage() {
  const { publicKey } = useWallet();
  const router = useRouter();
  const [form, setForm] = useState({
    title: "",
    description: "",
    prize_usdc: "",
    voting_start: "",
    voting_end: "",
    max_projects: "100",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!publicKey) return;
    setLoading(true);
    setError(null);

    try {
      const token = localStorage.getItem("seeker_token");
      const res = await fetch(`${API}/hackathons/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: form.title,
          description: form.description,
          prize_pool_usdc: Math.round(parseFloat(form.prize_usdc) * 1_000_000),
          voting_start: new Date(form.voting_start).toISOString(),
          voting_end: new Date(form.voting_end).toISOString(),
          max_projects: parseInt(form.max_projects),
        }),
      });

      if (!res.ok) throw new Error((await res.json()).detail);
      const hackathon = await res.json();
      router.push(`/hackathons/${hackathon.id}/fund`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-8">Create Hackathon</h1>

      {!publicKey && (
        <div className="mb-8 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-amber-800 mb-3">Connect your organizer wallet to continue</p>
          <WalletMultiButton />
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">
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

        <div className="grid grid-cols-2 gap-4">
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
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Max projects</label>
            <input
              type="number"
              required
              min="1"
              value={form.max_projects}
              onChange={(e) => setForm({ ...form, max_projects: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
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

        <button
          type="submit"
          disabled={!publicKey || loading}
          className="w-full bg-purple-600 text-white py-3 rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Creating..." : "Create Hackathon"}
        </button>
      </form>
    </div>
  );
}
