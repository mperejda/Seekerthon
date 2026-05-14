"use client";
import { use, useEffect, useState } from "react";
import { useConnection, useWallet } from "@solana/wallet-adapter-react";
import { Transaction } from "@solana/web3.js";
import { useUser } from "../../../providers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface Hackathon {
  status: string;
  voting_start: string;
  voting_end: string;
  title: string;
}

function submissionsOpen(h: Hackathon): boolean {
  return h.status === "open" && new Date() < new Date(h.voting_start);
}

function closedReason(h: Hackathon): string {
  if (h.status === "draft") return "This hackathon isn't open yet — the organizer hasn't funded the prize escrow.";
  if (h.status === "open" && new Date() >= new Date(h.voting_start))
    return `Submissions closed — the voting window opened ${new Date(h.voting_start).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}.`;
  if (h.status === "voting") return "Submissions are closed — this hackathon is in the voting phase.";
  if (h.status === "verifying") return "Submissions are closed — the organizer is verifying the winner.";
  if (h.status === "completed") return "This hackathon has ended.";
  return "This hackathon is not accepting submissions.";
}

export default function SubmitProjectPage({ params }: { params: Promise<{ hackathonId: string }> }) {
  const { hackathonId } = use(params);
  const { publicKey, signTransaction } = useWallet();
  const { connection } = useConnection();
  const user = useUser();
  const [hackathon, setHackathon] = useState<Hackathon | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [form, setForm] = useState({
    name: "",
    description: "",
    demo_url: "",
    repo_url: "",
    tech_stack: "",
  });
  const [files, setFiles] = useState<FileList | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/hackathons/${hackathonId}`)
      .then((r) => r.json())
      .then(setHackathon)
      .finally(() => setStatusLoading(false));
  }, [hackathonId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const token = localStorage.getItem("seeker_token");
      const res = await fetch(`${API}/projects/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          hackathon_id: hackathonId,
          name: form.name,
          description: form.description,
          demo_url: form.demo_url || null,
          repo_url: form.repo_url || null,
          tech_stack: form.tech_stack.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });

      if (!res.ok) throw new Error((await res.json()).detail);
      let project = await res.json();

      if (project.status === "pending_registration") {
        if (!signTransaction) {
          throw new Error("Wallet does not support transaction signing");
        }
        setUploadStatus("Preparing on-chain project registration...");
        const regRes = await fetch(`${API}/projects/${project.id}/register-tx`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!regRes.ok) throw new Error((await regRes.json()).detail);
        const { transaction_b64 } = await regRes.json();
        const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
        const tx = Transaction.from(txBytes);

        setUploadStatus("Waiting for wallet approval...");
        const signedTx = await signTransaction(tx);
        setUploadStatus("Submitting registration...");
        const sig = await connection.sendRawTransaction(signedTx.serialize(), {
          skipPreflight: false,
          preflightCommitment: "confirmed",
        });
        setUploadStatus("Confirming registration...");
        await connection.confirmTransaction(sig, "confirmed");

        const confirmRes = await fetch(`${API}/projects/${project.id}/register`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ tx_signature: sig }),
        });
        if (!confirmRes.ok) throw new Error((await confirmRes.json()).detail);
        project = await confirmRes.json();
      }

      setProjectId(project.id);

      if (files) {
        const fileList = Array.from(files);
        for (let i = 0; i < fileList.length; i++) {
          const file = fileList[i];
          setUploadStatus(`Uploading file ${i + 1} of ${fileList.length}…`);
          const fd = new FormData();
          fd.append("file", file);
          await fetch(`${API}/projects/${project.id}/assets`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
            body: fd,
          });
        }
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
      setUploadStatus(null);
    }
  };

  if (projectId) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <div className="text-5xl mb-4">🎉</div>
        <h2 className="text-2xl font-bold mb-2">Project submitted!</h2>
        <p className="text-gray-600">Your project is now visible to Seeker voters.</p>
        <p className="text-sm text-gray-400 mt-2">Project ID: {projectId}</p>
      </div>
    );
  }

  if (statusLoading) {
    return <div className="max-w-2xl mx-auto py-12 px-4 text-gray-400">Loading...</div>;
  }

  if (user === undefined) {
    return <div className="max-w-2xl mx-auto py-12 px-4 text-gray-400">Loading...</div>;
  }

  if (!user) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <h2 className="text-2xl font-bold mb-2">Connect your wallet</h2>
        <p className="text-gray-500 mb-6">Connect your wallet to submit a project.</p>
        <a href="/" className="inline-block mt-4 text-purple-600 hover:underline text-sm">← Back to hackathons</a>
      </div>
    );
  }

  if (!hackathon || !submissionsOpen(hackathon)) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <div className="text-5xl mb-4">🔒</div>
        <h2 className="text-2xl font-bold mb-2">Submissions closed</h2>
        <p className="text-gray-500">{hackathon ? closedReason(hackathon) : "Hackathon not found."}</p>
        <a href="/" className="inline-block mt-6 text-purple-600 hover:underline text-sm">← Back to hackathons</a>
      </div>
    );
  }

  const votingStartsAt = new Date(hackathon.voting_start);

  return (
    <div className="max-w-2xl mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-2">Submit Project</h1>
      <p className="text-sm text-gray-500 mb-8">
        Submissions close{" "}
        {votingStartsAt.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
        {" "}when voting begins.
      </p>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">{error}</div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm font-medium mb-1">Project name</label>
          <input
            type="text"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
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
            placeholder="What does your project do? What problem does it solve?"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Demo URL</label>
            <input
              type="url"
              value={form.demo_url}
              onChange={(e) => setForm({ ...form, demo_url: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="https://..."
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">GitHub / Repo</label>
            <input
              type="url"
              value={form.repo_url}
              onChange={(e) => setForm({ ...form, repo_url: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="https://github.com/..."
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Tech stack (comma separated)</label>
          <input
            type="text"
            value={form.tech_stack}
            onChange={(e) => setForm({ ...form, tech_stack: e.target.value })}
            className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="Rust, Anchor, React, Python"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Demo video / screenshots</label>
          <input
            type="file"
            multiple
            accept="video/*,image/*"
            onChange={(e) => setFiles(e.target.files)}
            className="w-full border rounded-lg px-3 py-2"
          />
          <p className="text-xs text-gray-500 mt-1">Upload a short demo video or screenshots. Max 50MB.</p>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-purple-600 text-white py-3 rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50"
        >
          {uploadStatus ?? (loading ? "Submitting..." : "Submit Project")}
        </button>
      </form>
    </div>
  );
}
