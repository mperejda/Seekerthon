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

interface Registration {
  project_id: string;
}

interface Project {
  status: string;
  name?: string;
}

interface RegistrationStatus {
  is_registered: boolean;
  registration: Registration | null;
  spots_remaining: number;
  spots_total: number;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${res.status})`);
  }
  return res.json();
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

function buildXPostUrl(projectName: string, hackathonTitle: string): string {
  const text = `I just submitted my ${projectName} to ${hackathonTitle} on Seekerthon.`;
  return `https://x.com/intent/tweet?${new URLSearchParams({ text }).toString()}`;
}

export default function SubmitProjectPage({ params }: { params: Promise<{ hackathonId: string }> }) {
  const { hackathonId } = use(params);
  const { publicKey, signTransaction } = useWallet();
  const { connection } = useConnection();
  const user = useUser();

  const [hackathon, setHackathon] = useState<Hackathon | null>(null);
  const [regStatus, setRegStatus] = useState<RegistrationStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);

  const [form, setForm] = useState({
    name: "",
    description: "",
    demo_url: "",
    repo_url: "",
    tech_stack: "",
  });
  const [videoFile, setVideoFile] = useState<File | null>(null);

  const [loading, setLoading] = useState(false);
  const [stepStatus, setStepStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<"registered" | "submitted" | null>(null);
  const [submittedProjectName, setSubmittedProjectName] = useState<string | null>(null);

  const isLoggedIn = !!user;

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      setStatusLoading(true);
      setError(null);
      try {
        const h = await fetchJson<Hackathon>(`${API}/hackathons/${hackathonId}`);
        if (cancelled) return;
        setHackathon(h);

        if (!isLoggedIn) {
          setRegStatus(null);
          return;
        }

        try {
          const reg = await fetchJson<RegistrationStatus>(`${API}/hackathons/${hackathonId}/registration`, {
            credentials: "include",
          });
          if (cancelled) return;
          setRegStatus(reg);

          if (reg.is_registered && reg.registration?.project_id) {
            try {
              const proj = await fetchJson<Project>(`${API}/projects/${reg.registration.project_id}`, {
                credentials: "include",
              });
              if (!cancelled && ["submitted", "approved", "winner"].includes(proj.status)) {
                setSubmittedProjectName(proj.name || null);
                setDone("submitted");
              }
            } catch {
              // project fetch failing shouldn't block the page
            }
          }
        } catch (err) {
          console.error("Failed to load registration status", err);
          if (!cancelled) {
            setRegStatus(null);
            setError("Could not load your registration status. You can refresh or try again in a moment.");
          }
        }
      } catch (err: any) {
        if (!cancelled) setError(err.message ?? "Failed to load hackathon");
      } finally {
        if (!cancelled) setStatusLoading(false);
      }
    }

    loadStatus();
    return () => {
      cancelled = true;
    };
  }, [hackathonId, isLoggedIn]);

  const handleRegister = async () => {
    setLoading(true);
    setError(null);
    try {
      const prepRes = await fetch(`${API}/hackathons/${hackathonId}/register-tx`, {
        credentials: "include",
      });
      if (!prepRes.ok) throw new Error((await prepRes.json()).detail);
      const { transaction_b64, project_id } = await prepRes.json();

      let tx_signature: string | null = null;

      if (transaction_b64) {
        if (!signTransaction) throw new Error("Wallet does not support transaction signing");
        setStepStatus("Waiting for wallet approval…");
        const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
        const tx = Transaction.from(txBytes);
        const signed = await signTransaction(tx);
        setStepStatus("Submitting registration…");
        tx_signature = await connection.sendRawTransaction(signed.serialize(), {
          skipPreflight: false,
          preflightCommitment: "confirmed",
        });
        setStepStatus("Confirming on-chain…");
        await connection.confirmTransaction(tx_signature, "confirmed");
      }

      setStepStatus("Locking in your spot…");
      const confirmRes = await fetch(`${API}/hackathons/${hackathonId}/register`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id, tx_signature }),
      });
      if (!confirmRes.ok) throw new Error((await confirmRes.json()).detail);

      setRegStatus({ is_registered: true, registration: { project_id }, spots_remaining: 0, spots_total: 100 });
      setDone("registered");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
      setStepStatus(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const projectId = regStatus?.registration?.project_id;
    if (!projectId) return;

    try {
      setStepStatus("Saving project details…");
      const res = await fetch(`${API}/projects/${projectId}/submit`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          description: form.description,
          demo_url: form.demo_url || null,
          repo_url: form.repo_url || null,
          tech_stack: form.tech_stack.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      const { transaction_b64 } = await res.json();

      if (transaction_b64) {
        if (!signTransaction) throw new Error("Wallet does not support transaction signing");
        setStepStatus("Waiting for wallet approval…");
        const txBytes = Uint8Array.from(atob(transaction_b64), (c) => c.charCodeAt(0));
        const tx = Transaction.from(txBytes);
        const signed = await signTransaction(tx);
        setStepStatus("Confirming on-chain…");
        const txSig = await connection.sendRawTransaction(signed.serialize(), {
          skipPreflight: false,
          preflightCommitment: "confirmed",
        });
        await connection.confirmTransaction(txSig, "confirmed");
        setStepStatus("Finalizing submission…");
        const confirmRes = await fetch(`${API}/projects/${projectId}/submit/confirm`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tx_signature: txSig }),
        });
        if (!confirmRes.ok) throw new Error((await confirmRes.json()).detail);
      }

      if (videoFile) {
        setStepStatus("Requesting upload URL…");
        const urlRes = await fetch(`${API}/projects/${projectId}/video-upload-url`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: videoFile.name, content_type: "video/mp4" }),
        });
        if (!urlRes.ok) throw new Error((await urlRes.json()).detail);
        const { upload_url, key } = await urlRes.json();

        setStepStatus("Uploading video…");
        const putRes = await fetch(upload_url, {
          method: "PUT",
          headers: { "Content-Type": "video/mp4" },
          body: videoFile,
        });
        if (!putRes.ok) throw new Error("Video upload failed");

        setStepStatus("Verifying video content…");
        const confirmRes = await fetch(`${API}/projects/${projectId}/video-confirm`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key }),
        });
        if (!confirmRes.ok) throw new Error((await confirmRes.json()).detail);
      }

      setSubmittedProjectName(form.name);
      setDone("submitted");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
      setStepStatus(null);
    }
  };

  // ── Loading / auth guards ───────────────────────────────────────────────────

  if (statusLoading || user === undefined) {
    return <div className="max-w-2xl mx-auto py-12 px-4 text-gray-400">Loading...</div>;
  }

  if (!user) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <h2 className="text-2xl font-bold mb-2">Connect your wallet</h2>
        <p className="text-gray-500 mb-6">Connect your wallet to register or submit a project.</p>
        <a href="/" className="inline-block mt-4 text-purple-600 hover:underline text-sm">← Back to hackathons</a>
      </div>
    );
  }

  if (!hackathon) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <h2 className="text-2xl font-bold mb-2">Hackathon unavailable</h2>
        <p className="text-gray-500">{error ?? "Hackathon not found."}</p>
        <a href="/" className="inline-block mt-6 text-purple-600 hover:underline text-sm">← Back to hackathons</a>
      </div>
    );
  }

  if (!submissionsOpen(hackathon)) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <div className="text-5xl mb-4">🔒</div>
        <h2 className="text-2xl font-bold mb-2">Submissions closed</h2>
        <p className="text-gray-500">{closedReason(hackathon)}</p>
        <a href="/" className="inline-block mt-6 text-purple-600 hover:underline text-sm">← Back to hackathons</a>
      </div>
    );
  }

  // ── Success states ──────────────────────────────────────────────────────────

  if (done === "submitted") {
    const projectName = submittedProjectName || form.name || "project";
    const xPostUrl = buildXPostUrl(projectName, hackathon.title);

    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <div className="text-5xl mb-4">🎉</div>
        <h2 className="text-2xl font-bold mb-2">Project submitted!</h2>
        <p className="text-gray-600 mb-8">Your project will be visible to Seeker voters once voting begins.</p>
        <div className="flex flex-col items-center gap-4">
          <a
            href={xPostUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-black px-5 py-2.5 text-sm font-medium text-white hover:bg-gray-800"
          >
            <span className="font-bold">X</span>
            <span>Post on X</span>
          </a>
          <a href="/" className="text-purple-600 hover:underline text-sm">← Back to hackathons</a>
        </div>
      </div>
    );
  }

  if (done === "registered") {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <div className="text-5xl mb-4">✅</div>
        <h2 className="text-2xl font-bold mb-2">Spot locked in!</h2>
        <p className="text-gray-600 mb-6">You're registered. Come back before voting starts to fill in your project details.</p>
        <a href="/" className="inline-block text-purple-600 hover:underline text-sm">← Back to hackathons</a>
      </div>
    );
  }

  const votingStartsAt = new Date(hackathon.voting_start);
  const deadlineStr = votingStartsAt.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const isRegistered = regStatus?.is_registered ?? false;
  const projectId = regStatus?.registration?.project_id ?? null;

  // ── Step 1: Register ────────────────────────────────────────────────────────

  if (!isRegistered) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4">
        <a href="/" className="text-sm text-gray-400 hover:text-gray-600 mb-6 inline-block">← Back to hackathons</a>
        <h1 className="text-3xl font-bold mb-2">Register for {hackathon.title}</h1>
        <p className="text-sm text-gray-500 mb-8">
          Lock in your spot on-chain before voting begins {deadlineStr}. You can fill in project details after registering.
        </p>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">{error}</div>
        )}

        {regStatus && (
          <p className="text-sm text-gray-400 mb-6">
            {regStatus.spots_remaining} of {regStatus.spots_total} spots remaining
          </p>
        )}

        <button
          onClick={handleRegister}
          disabled={loading || !publicKey}
          className="w-full bg-purple-600 text-white py-3 rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50"
        >
          {stepStatus ?? (loading ? "Registering…" : "Lock In My Spot — $2 USDC")}
        </button>
        <p className="text-xs text-gray-400 mt-2 text-center">
          A $2 USDC registration fee covers content moderation and platform costs.
        </p>
        {!publicKey && (
          <p className="text-xs text-gray-400 mt-2 text-center">Connect your wallet above to register.</p>
        )}
      </div>
    );
  }

  // ── Step 2: Submit details ──────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto py-12 px-4">
      <a href="/" className="text-sm text-gray-400 hover:text-gray-600 mb-6 inline-block">← Back to hackathons</a>
      <h1 className="text-3xl font-bold mb-2">Submit Project</h1>
      <p className="text-sm text-gray-500 mb-8">
        You're registered. Fill in your project details before voting begins {deadlineStr}.
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
              required
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
              required
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
            required
            value={form.tech_stack}
            onChange={(e) => setForm({ ...form, tech_stack: e.target.value })}
            className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="Rust, Anchor, React, Python"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Demo video</label>
          <input
            type="file"
            accept="video/mp4"
            onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
            className="w-full border rounded-lg px-3 py-2"
          />
          <p className="text-xs text-gray-500 mt-1">Upload a short MP4 demo video. Max 50MB.</p>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-purple-600 text-white py-3 rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50"
        >
          {stepStatus ?? (loading ? "Submitting…" : "Submit Project")}
        </button>
      </form>
    </div>
  );
}
