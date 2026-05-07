"use client";
import { use, useEffect, useState } from "react";
import { useWallet, useConnection } from "@solana/wallet-adapter-react";
import dynamic from "next/dynamic";
const WalletMultiButton = dynamic(
  async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton,
  { ssr: false }
);
import { Transaction } from "@solana/web3.js";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface Hackathon {
  title: string;
  description: string;
  status: string;
  prize_pool_usdc: number;
  voting_start: string;
  voting_end: string;
}

interface Project {
  id: string;
  name: string;
  description: string;
  demo_url: string | null;
  repo_url: string | null;
  tech_stack: string[];
  vote_count: number;
  status: string;
}

export default function OrganizerDashboard({ params }: { params: Promise<{ hackathonId: string }> }) {
  const { hackathonId } = use(params);
  const { publicKey, sendTransaction } = useWallet();
  const { connection } = useConnection();

  const [projects, setProjects] = useState<Project[]>([]);
  const [hackathon, setHackathon] = useState<Hackathon | null>(null);
  const hackathonStatus = hackathon?.status ?? null;
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState<string | null>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("seeker_token");
    fetch(`${API}/hackathons/${hackathonId}`)
      .then((r) => r.ok ? r.json() : null)
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

  const setStatus = async (status: string) => {
    setStatusUpdating(true);
    setError(null);
    try {
      const res = await fetch(`${API}/hackathons/${hackathonId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("seeker_token")}` },
        body: JSON.stringify({ status }),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      const h = await res.json();
      setHackathon(h);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setStatusUpdating(false);
    }
  };

  const verifyAndRelease = async (projectId: string) => {
    setVerifying(projectId);
    setError(null);
    const token = localStorage.getItem("seeker_token");

    try {
      // Step 1: get the unsigned release transaction from the backend
      const prepRes = await fetch(
        `${API}/hackathons/${hackathonId}/verify/${projectId}/release-tx`,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      let txSignature: string | undefined;

      if (prepRes.ok) {
        // Hackathon has an on-chain escrow — sign and send the release tx
        const { transaction_b64 } = await prepRes.json();
        const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
        const tx = Transaction.from(txBytes);

        txSignature = await sendTransaction(tx, connection, {
          skipPreflight: false,
        });

        // Wait for confirmation before calling the backend confirm step
        await connection.confirmTransaction(txSignature, "confirmed");
      } else if (prepRes.status !== 400) {
        // Unexpected error from the prepare endpoint
        throw new Error((await prepRes.json()).detail);
      }
      // If 400 (no escrow set up), fall through with no signature — dev/test mode

      // Step 2: confirm with the backend (updates DB, verifies on-chain if escrow exists)
      const confirmRes = await fetch(
        `${API}/hackathons/${hackathonId}/verify/${projectId}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ tx_signature: txSignature ?? null }),
        }
      );
      if (!confirmRes.ok) throw new Error((await confirmRes.json()).detail);

      setProjects((prev) =>
        prev.map((p) => (p.id === projectId ? { ...p, status: "winner" } : p))
      );
    } catch (err: any) {
      setError(err.message);
    } finally {
      setVerifying(null);
    }
  };

  const votingEnded = hackathon ? new Date() >= new Date(hackathon.voting_end) : false;
  const sorted = [...projects].sort((a, b) => b.vote_count - a.vote_count);

  return (
    <div className="max-w-4xl mx-auto py-12 px-4">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-3xl font-bold">{hackathon?.title ?? "Organizer Dashboard"}</h1>
        <WalletMultiButton />
      </div>
      {hackathon && (
        <div className="flex gap-4 text-sm text-gray-500 mb-2">
          <span>${(hackathon.prize_pool_usdc / 1_000_000).toLocaleString("en-US")} USDC prize</span>
          <span>Voting {new Date(hackathon.voting_start).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} – {new Date(hackathon.voting_end).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
        </div>
      )}
      <div className="flex items-center gap-3 mb-8">
        <p className="text-gray-500 text-sm">Review submissions and release prizes to winners</p>
        {hackathonStatus && (
          <span className="text-xs font-medium px-2 py-1 rounded-full bg-gray-100 text-gray-600 capitalize">{hackathonStatus}</span>
        )}
        {hackathonStatus === "draft" && (
          <a
            href={`/hackathons/${hackathonId}/fund`}
            className="text-sm bg-purple-600 text-white px-4 py-1.5 rounded-lg hover:bg-purple-700"
          >
            Fund Escrow to Open
          </a>
        )}
        {hackathonStatus === "open" && (
          <button
            onClick={() => setStatus("voting")}
            disabled={statusUpdating}
            className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {statusUpdating ? "Updating..." : "Start voting"}
          </button>
        )}
      </div>

      {hackathonStatus === "voting" && !votingEnded && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg text-blue-800">
          <strong>Voting in progress.</strong> Verify &amp; Release will become available once the voting period ends.
        </div>
      )}
      {hackathonStatus === "voting" && votingEnded && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg text-green-800">
          <strong>Voting has ended.</strong> Review the leaderboard below and click <em>Verify &amp; Release Prize</em> on the winning project.
        </div>
      )}
      {hackathonStatus === "verifying" && (
        <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-800">
          <strong>Waiting on verification.</strong> Sign the release transaction to send the prize to the winner.
        </div>
      )}
      {hackathonStatus === "completed" && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg text-green-800">
          <strong>Hackathon complete.</strong> The prize has been released to the winner.
        </div>
      )}

      {!publicKey && hackathonStatus === "voting" && (
        <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-800">
          Connect your organizer wallet above to sign the prize release transaction.
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-20 text-gray-400">Loading projects...</div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-20">
          <p className="text-gray-400 mb-4">No projects submitted yet.</p>
          <a
            href={`/projects/submit/${hackathonId}`}
            className="bg-purple-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-purple-700"
          >
            Submit the first project
          </a>
        </div>
      ) : (
        <div className="space-y-4">
          {sorted.map((project, idx) => (
            <div
              key={project.id}
              className={`p-6 border rounded-xl ${
                project.status === "winner" ? "border-yellow-400 bg-yellow-50" : "border-gray-200 bg-white"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="text-2xl font-bold text-gray-300">#{idx + 1}</span>
                    <h3 className="text-lg font-semibold">{project.name}</h3>
                    {project.status === "winner" && (
                      <span className="bg-yellow-400 text-yellow-900 text-xs font-medium px-2 py-1 rounded-full">
                        Winner
                      </span>
                    )}
                  </div>
                  <p className="text-gray-600 text-sm mb-3">{project.description}</p>
                  <div className="flex gap-3 flex-wrap">
                    {project.tech_stack.map((t) => (
                      <span key={t} className="bg-gray-100 text-gray-600 text-xs px-2 py-1 rounded">
                        {t}
                      </span>
                    ))}
                  </div>
                  <div className="flex gap-4 mt-3">
                    {project.demo_url && (
                      <a href={project.demo_url} target="_blank" rel="noopener noreferrer"
                        className="text-purple-600 text-sm hover:underline">
                        Demo
                      </a>
                    )}
                    {project.repo_url && (
                      <a href={project.repo_url} target="_blank" rel="noopener noreferrer"
                        className="text-purple-600 text-sm hover:underline">
                        Repo
                      </a>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-2xl font-bold text-purple-600">{project.vote_count.toFixed(1)}</div>
                  <div className="text-xs text-gray-400 mb-3">weighted votes</div>
                  {project.status !== "winner" && votingEnded && idx === 0 && (
                    <button
                      onClick={() => verifyAndRelease(project.id)}
                      disabled={verifying === project.id || !publicKey}
                      className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                      title={!publicKey ? "Connect your wallet first" : undefined}
                    >
                      {verifying === project.id ? "Releasing..." : "Verify & Release Prize"}
                    </button>
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
