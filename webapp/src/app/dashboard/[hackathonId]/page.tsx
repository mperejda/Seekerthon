"use client";
import { use, useEffect, useState } from "react";
import { useWallet, useConnection } from "@solana/wallet-adapter-react";
import { useUser } from "../../providers";
import dynamic from "next/dynamic";
const WalletMultiButton = dynamic(
  async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton,
  { ssr: false }
);
import { Transaction, SendTransactionError } from "@solana/web3.js";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function extractTxError(err: unknown, connection: import("@solana/web3.js").Connection): Promise<string> {
  if (err instanceof SendTransactionError) {
    let logs: string[] | null = null;
    try { logs = await err.getLogs(connection); } catch { logs = err.logs ?? null; }
    if (logs) {
      const anchor = logs.find((l) => l.includes("AnchorError") || l.includes("Error Message:"));
      if (anchor) {
        const match = anchor.match(/Error Message: (.+)$/);
        if (match) return match[1];
      }
    }
    return err.message;
  }
  return (err as any)?.message ?? String(err);
}

interface Hackathon {
  organizer_id: string;
  title: string;
  description: string;
  status: string;
  prize_pool_usdc: number;
  voting_start: string;
  voting_end: string;
}

interface Project {
  id: string;
  team_lead_id: string;
  name: string;
  description: string;
  demo_url: string | null;
  repo_url: string | null;
  tech_stack: string[];
  vote_count: number;
  status: string;
}

function displayHackathonStatus(hackathon: Hackathon | null): string | null {
  if (!hackathon) return null;
  const now = new Date();
  const votingStart = new Date(hackathon.voting_start);
  const votingEnd = new Date(hackathon.voting_end);
  if (hackathon.status === "completed") return "completed";
  if (hackathon.status === "draft") return "draft";
  if (now < votingStart) return "accepting_submissions";
  if (now < votingEnd) return "voting";
  if (hackathon.status === "verifying" || hackathon.status === "open" || hackathon.status === "voting") return "verifying";
  return hackathon.status;
}

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  accepting_submissions: "Accepting submissions",
  open: "Open",
  voting: "Voting in progress",
  verifying: "Voting ended",
  completed: "Complete",
};

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600",
  accepting_submissions: "bg-green-100 text-green-700",
  open: "bg-green-100 text-green-700",
  voting: "bg-blue-100 text-blue-700",
  verifying: "bg-green-100 text-green-700",
  completed: "bg-purple-100 text-purple-700",
};

function buildWinnerXPostUrl(projectName: string, hackathonTitle: string): string {
  const text = `${projectName} just won ${hackathonTitle} on Seekerthon.`;
  return `https://x.com/intent/tweet?${new URLSearchParams({ text }).toString()}`;
}

export default function ResultsDashboard({ params }: { params: Promise<{ hackathonId: string }> }) {
  const { hackathonId } = use(params);
  const { publicKey, signTransaction } = useWallet();
  const { connection } = useConnection();
  const user = useUser();
  const [projects, setProjects] = useState<Project[]>([]);
  const [hackathon, setHackathon] = useState<Hackathon | null>(null);
  const [loading, setLoading] = useState(true);
  const [claiming, setClaiming] = useState<string | null>(null);
  const [refunding, setRefunding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/hackathons/${hackathonId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => h && setHackathon(h));
    fetch(`${API}/projects/hackathon/${hackathonId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load projects (${r.status})`);
        return r.json();
      })
      .then(setProjects)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [hackathonId]);

  if (user === undefined) {
    return <div className="text-center py-20 text-gray-400">Loading...</div>;
  }
  if (user === null) {
    return (
      <div className="max-w-4xl mx-auto py-12 px-4 text-center">
        <h1 className="text-2xl font-bold text-gray-900 mb-3">Connect your wallet</h1>
        <p className="text-gray-500 mb-6">Sign in to view results or claim a prize.</p>
        <WalletMultiButton />
      </div>
    );
  }

  const hackathonStatus = displayHackathonStatus(hackathon);
  const votingEnded = hackathon ? new Date() >= new Date(hackathon.voting_end) : false;
  const storedHackathonStatus = hackathon?.status ?? null;
  const sorted = [...projects].sort((a, b) => b.vote_count - a.vote_count);
  const isOrganizer = !!hackathon && user.id === hackathon.organizer_id;

  const claimPrize = async (projectId: string) => {
    setClaiming(projectId);
    setError(null);
    try {
      const prepRes = await fetch(`${API}/hackathons/${hackathonId}/claim/${projectId}/tx`, {
        credentials: "include",
      });
      if (!prepRes.ok) throw new Error((await prepRes.json()).detail);
      const { transaction_b64 } = await prepRes.json();
      const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
      const tx = Transaction.from(txBytes);
      if (!signTransaction) throw new Error("Wallet does not support signing");
      const signed = await signTransaction(tx);
      const txSignature = await connection.sendRawTransaction(signed.serialize(), { skipPreflight: false, preflightCommitment: "confirmed" });

      const confirmRes = await fetch(`${API}/hackathons/${hackathonId}/claim/${projectId}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tx_signature: txSignature }),
      });
      if (!confirmRes.ok) {
        const body = await confirmRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Server error (${confirmRes.status})`);
      }
      setHackathon(await confirmRes.json());
      setProjects((prev) => prev.map((p) => (p.id === projectId ? { ...p, status: "winner" } : p)));
    } catch (err: any) {
      setError(await extractTxError(err, connection));
    } finally {
      setClaiming(null);
    }
  };

  const refundOrganizer = async () => {
    setRefunding(true);
    setError(null);
    try {
      const prepRes = await fetch(`${API}/hackathons/${hackathonId}/verify/refund/release-tx`, {
        credentials: "include",
      });
      if (!prepRes.ok) throw new Error((await prepRes.json()).detail);
      const { transaction_b64 } = await prepRes.json();
      const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
      const tx = Transaction.from(txBytes);
      if (!signTransaction) throw new Error("Wallet does not support signing");
      const signed = await signTransaction(tx);
      const txSignature = await connection.sendRawTransaction(signed.serialize(), { skipPreflight: false, preflightCommitment: "confirmed" });

      const confirmRes = await fetch(`${API}/hackathons/${hackathonId}/verify/refund`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tx_signature: txSignature }),
      });
      if (!confirmRes.ok) {
        const body = await confirmRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Server error (${confirmRes.status})`);
      }
      setHackathon(await confirmRes.json());
    } catch (err: any) {
      setError(await extractTxError(err, connection));
    } finally {
      setRefunding(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto py-12 px-4">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-3xl font-bold">{hackathon?.title ?? "Hackathon Results"}</h1>
        <WalletMultiButton />
      </div>
      {hackathon && (
        <div className="flex gap-4 text-sm text-gray-500 mb-2">
          <span>${(hackathon.prize_pool_usdc / 1_000_000).toLocaleString("en-US")} USDC prize</span>
          <span>
            Voting {new Date(hackathon.voting_start).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} - {new Date(hackathon.voting_end).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
          </span>
        </div>
      )}
      <div className="flex items-center gap-3 mb-8">
        <p className="text-gray-500 text-sm">Review submissions and claim prizes</p>
        {hackathonStatus && (
          <span className={`text-xs font-medium px-2 py-1 rounded-full ${STATUS_BADGE[hackathonStatus] ?? STATUS_BADGE.draft}`}>
            {STATUS_LABEL[hackathonStatus] ?? hackathonStatus}
          </span>
        )}
      </div>

      {hackathonStatus === "voting" && !votingEnded && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg text-blue-800">
          <strong>Voting in progress.</strong> Prize claiming becomes available once the voting period ends.
        </div>
      )}
      {hackathonStatus === "accepting_submissions" && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg text-green-800">
          <strong>Accepting submissions.</strong> Builders can submit projects until voting starts.
        </div>
      )}
      {hackathonStatus === "verifying" && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg text-green-800">
          <strong>Voting has ended.</strong>{" "}
          {sorted.length === 0
            ? "No projects were submitted. The organizer can reclaim the prize pool below."
            : "The prize is ready to be claimed by the winner."}
        </div>
      )}
      {hackathonStatus === "completed" && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg text-green-800">
          <strong>Hackathon complete.</strong> The prize pool has been released.
        </div>
      )}
      {error && <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">{error}</div>}

      {loading ? (
        <div className="text-center py-20 text-gray-400">Loading projects...</div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-20">
          <p className="text-gray-400 mb-4">No registered projects submitted yet.</p>
          {isOrganizer && hackathonStatus === "verifying" && (
            <button onClick={refundOrganizer} disabled={refunding || !publicKey} className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50">
              {refunding ? "Refunding..." : "Refund Prize to Organizer"}
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {sorted.map((project, idx) => (
            <div key={project.id} className={`p-6 border rounded-xl ${project.status === "winner" ? "border-yellow-400 bg-yellow-50" : "border-gray-200 bg-white"}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="text-2xl font-bold text-gray-300">#{idx + 1}</span>
                    <h3 className="text-lg font-semibold">{project.name}</h3>
                    {project.status === "winner" && <span className="bg-yellow-400 text-yellow-900 text-xs font-medium px-2 py-1 rounded-full">Winner</span>}
                  </div>
                  <p className="text-gray-600 text-sm mb-3">{project.description}</p>
                  <div className="flex gap-3 flex-wrap">
                    {project.tech_stack.map((t) => <span key={t} className="bg-gray-100 text-gray-600 text-xs px-2 py-1 rounded">{t}</span>)}
                  </div>
                  <div className="flex gap-4 mt-3">
                    {project.demo_url && <a href={project.demo_url} target="_blank" rel="noopener noreferrer" className="text-purple-600 text-sm hover:underline">Demo</a>}
                    {project.repo_url && <a href={project.repo_url} target="_blank" rel="noopener noreferrer" className="text-purple-600 text-sm hover:underline">Repo</a>}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-2xl font-bold text-purple-600">{project.vote_count.toFixed(1)}</div>
                  <div className="text-xs text-gray-400 mb-3">weighted votes</div>
                  {project.status !== "winner" && votingEnded && idx === 0 && user.id === project.team_lead_id && (
                    <button onClick={() => claimPrize(project.id)} disabled={claiming === project.id || !publicKey} className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50">
                      {claiming === project.id ? "Claiming..." : "Claim Prize"}
                    </button>
                  )}
                  {project.status === "winner" && user.id === project.team_lead_id && hackathon && (
                    <a
                      href={buildWinnerXPostUrl(project.name, hackathon.title)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center justify-center gap-2 rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
                    >
                      <span className="font-bold">X</span>
                      <span>Post Win</span>
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
