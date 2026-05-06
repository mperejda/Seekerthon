-- ============================================================
-- Migration 002: DB-backed challenge store, pending votes,
--                votes timestamp, updated leaderboard RPC
-- ============================================================

-- ── Challenge store (replaces in-memory dict) ──────────────
create table if not exists challenges (
  challenge   text primary key,
  expires_at  timestamptz not null
);

create index if not exists challenges_expires_idx on challenges(expires_at);

alter table challenges enable row level security;
-- No public policies — service role only

-- ── Pending votes: lock weight at prepare time ─────────────
create table if not exists pending_votes (
  voter_id    uuid not null references users(id),
  project_id  uuid not null references projects(id) on delete cascade,
  weight      float not null,
  expires_at  timestamptz not null,
  primary key (voter_id, project_id)
);

alter table pending_votes enable row level security;
-- No public policies — service role only

-- ── votes: add updated_at ──────────────────────────────────
alter table votes add column if not exists updated_at timestamptz not null default now();

create trigger votes_updated_at before update on votes
  for each row execute function update_updated_at();

-- ── Updated leaderboard RPC (returns all project fields) ───
drop function if exists get_leaderboard(uuid);

create or replace function get_leaderboard(p_hackathon_id uuid)
returns table (
  rank                bigint,
  id                  uuid,
  hackathon_id        uuid,
  team_lead_id        uuid,
  name                text,
  description         text,
  demo_url            text,
  repo_url            text,
  tech_stack          text[],
  storage_asset_ids   text[],
  onchain_pda         text,
  status              project_status,
  vote_count          float,
  created_at          timestamptz,
  total_votes         float,
  unique_voters       bigint
) language sql security definer as $$
  select
    row_number() over (order by p.vote_count desc) as rank,
    p.id,
    p.hackathon_id,
    p.team_lead_id,
    p.name,
    p.description,
    p.demo_url,
    p.repo_url,
    p.tech_stack,
    p.storage_asset_ids,
    p.onchain_pda,
    p.status,
    p.vote_count,
    p.created_at,
    p.vote_count      as total_votes,
    count(v.id)       as unique_voters
  from projects p
  left join votes v on v.project_id = p.id
  where p.hackathon_id = p_hackathon_id
  group by p.id
  order by p.vote_count desc;
$$;
