"use client";
import { use, useEffect, useState } from "react";
import { useWallet } from "@solana/wallet-adapter-react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const STATUS_MESSAGE: Record<string, string> = {
  draft:     "This hackathon isn't open yet — the organizer hasn't funded the prize escrow.",
  voting:    "Submissions are closed — this hackathon is in the voting phase.",
  verifying: "Submissions are closed — the organizer is verifying the winner.",
  completed: "This hackathon has ended.",
};

export default function SubmitProjectPage({ params }: { params: Promise<{ hackathonId: string }> }) {
  const { hackathonId } = use(params);
  const { publicKey } = useWallet();
  const [hackathonStatus, setHackathonStatus] = useState<string | null>(null);
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
  const [projectId, setProjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/hackathons/${hackathonId}`)
      .then((r) => r.json())
      .then((h) => setHackathonStatus(h.status))
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
      const project = await res.json();
      setProjectId(project.id);

      if (files) {
        for (const file of Array.from(files)) {
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

  if (hackathonStatus !== "open") {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <div className="text-5xl mb-4">🔒</div>
        <h2 className="text-2xl font-bold mb-2">Submissions closed</h2>
        <p className="text-gray-500">{STATUS_MESSAGE[hackathonStatus ?? ""] ?? "This hackathon is not accepting submissions."}</p>
        <a href="/" className="inline-block mt-6 text-purple-600 hover:underline text-sm">← Back to hackathons</a>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-8">Submit Project</h1>

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
          {loading ? "Submitting..." : "Submit Project"}
        </button>
      </form>
    </div>
  );
}
