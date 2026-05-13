"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useUser } from "./providers";

const WalletMultiButton = dynamic(
  async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton,
  { ssr: false }
);

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface Hackathon {
  id: string;
  organizer_id: string;
  title: string;
  description: string;
  status: string;
  prize_pool_usdc: number;
  voting_start: string;
  voting_end: string;
  project_count: number;
}

function submissionsOpen(h: Hackathon): boolean {
  return h.status === "open" && new Date() < new Date(h.voting_start);
}

function displayStatus(h: Hackathon): string {
  const now = new Date();
  const votingStart = new Date(h.voting_start);
  const votingEnd = new Date(h.voting_end);

  if (h.status === "completed") return "completed";
  if (h.status === "draft") return "draft";
  if (now < votingStart) return "accepting_submissions";
  if (now < votingEnd) return "voting";
  if (h.status === "verifying" || h.status === "open" || h.status === "voting") return "verifying";
  return h.status;
}

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600",
  accepting_submissions: "bg-green-100 text-green-700",
  open: "bg-green-100 text-green-700",
  voting: "bg-blue-100 text-blue-700",
  verifying: "bg-yellow-100 text-yellow-700",
  completed: "bg-purple-100 text-purple-700",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  accepting_submissions: "Accepting submissions",
  open: "Open",
  voting: "Voting in progress",
  verifying: "Verification in progress",
  completed: "Complete",
};

export default function HomePage() {
  const user = useUser();
  const [hackathons, setHackathons] = useState<Hackathon[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/hackathons/`)
      .then((r) => {
        if (!r.ok) throw new Error(`API error ${r.status}`);
        return r.json();
      })
      .then(setHackathons)
      .catch((e) => setFetchError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-4xl mx-auto py-12 px-4">
      <div className="flex items-center justify-between mb-10">
        <div>
          <h1 className="text-4xl font-bold text-gray-900">Seekerthon</h1>
          <p className="text-gray-500 mt-1">
            Seeker Genesis NFT holders vote with weighted $SKR power
          </p>
        </div>
        <WalletMultiButton />
      </div>

      {fetchError && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">
          Failed to load hackathons: {fetchError}
        </div>
      )}

      {loading ? (
        <div className="text-center py-20 text-gray-400">Loading...</div>
      ) : hackathons.length === 0 ? (
        <div className="text-center py-20">
          <p className="text-gray-400 mb-4">No hackathons yet.</p>
          <a
            href="/hackathons/create"
            className="bg-purple-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-purple-700"
          >
            Create the first one
          </a>
        </div>
      ) : (
        <div className="space-y-4">
          {hackathons.map((h) => {
            const status = displayStatus(h);

            return (
              <div
                key={h.id}
                className="bg-white border border-gray-200 rounded-xl p-6 hover:shadow-sm transition-shadow"
              >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h2 className="text-lg font-semibold text-gray-900">
                      {h.title}
                    </h2>
                    <span
                      className={`text-xs font-medium px-2 py-1 rounded-full ${
                        STATUS_BADGE[status] ?? STATUS_BADGE.draft
                      }`}
                    >
                      {STATUS_LABEL[status] ?? status}
                    </span>
                  </div>
                  <p className="text-gray-600 text-sm mb-3">{h.description}</p>
                  <div className="flex gap-6 text-xs text-gray-400">
                    <span>{h.project_count ?? 0} projects</span>
                    <span>
                      ${(h.prize_pool_usdc / 1_000_000).toLocaleString()} USDC prize
                    </span>
                    <span>
                      Voting:{" "}
                      {new Date(h.voting_start).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} –{" "}
                      {new Date(h.voting_end).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                    </span>
                  </div>
                </div>
                <div className="flex flex-col gap-2 shrink-0">
                  {submissionsOpen(h) && (
                    <a
                      href={`/projects/submit/${h.id}`}
                      className="text-sm bg-purple-50 text-purple-700 px-4 py-2 rounded-lg hover:bg-purple-100 text-center"
                    >
                      Submit Project
                    </a>
                  )}
                  {user && h.organizer_id === user.id && (
                    <a
                      href={`/dashboard/${h.id}`}
                      className="text-sm text-gray-500 px-4 py-2 rounded-lg hover:bg-gray-100 text-center"
                    >
                      Organizer View
                    </a>
                  )}
                </div>
              </div>
            </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
