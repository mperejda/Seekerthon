-- ============================================================
-- Seeker Hackathon Platform — Supabase Migration 001
-- ============================================================

-- Extensions
create extension if not exists "pgcrypto";

-- ── Users ──────────────────────────────────────────────────
create table if not exists users (
  id                  uuid primary key default gen_random_uuid(),
  wallet_address      text unique not null,
  skr_balance         bigint not null default 0,
  skr_staked          bigint not null default 0,
  vote_multiplier     float not null default 1.0,
  is_seeker_verified  boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create index if not exists users_wallet_idx on users(wallet_address);

-- ── Hackathons ─────────────────────────────────────────────
create type hackathon_status as enum ('draft','open','voting','verifying','completed');

create table if not exists hackathons (
  id                    uuid primary key default gen_random_uuid(),
  organizer_id          uuid not null references users(id),
  title                 text not null,
  description           text not null default '',
  prize_pool_lamports   bigint not null default 0,
  escrow_pubkey         text,
  onchain_pda           text,
  status                hackathon_status not null default 'draft',
  voting_start          timestamptz not null,
  voting_end            timestamptz not null,
  max_projects          int not null default 100,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists hackathons_status_idx on hackathons(status);
create index if not exists hackathons_organizer_idx on hackathons(organizer_id);

-- ── Projects ───────────────────────────────────────────────
create type project_status as enum ('submitted','approved','winner','rejected');

create table if not exists projects (
  id                  uuid primary key default gen_random_uuid(),
  hackathon_id        uuid not null references hackathons(id) on delete cascade,
  team_lead_id        uuid not null references users(id),
  name                text not null,
  description         text not null default '',
  demo_url            text,
  repo_url            text,
  tech_stack          text[] not null default '{}',
  storage_asset_ids   text[] not null default '{}',
  onchain_pda         text,
  status              project_status not null default 'submitted',
  vote_count          float not null default 0,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique(hackathon_id, team_lead_id)
);

create index if not exists projects_hackathon_idx on projects(hackathon_id);
create index if not exists projects_vote_count_idx on projects(vote_count desc);

-- ── Votes ──────────────────────────────────────────────────
create table if not exists votes (
  id            uuid primary key default gen_random_uuid(),
  voter_id      uuid not null references users(id),
  project_id    uuid not null references projects(id) on delete cascade,
  weight        float not null default 1.0,
  tx_signature  text unique not null,
  created_at    timestamptz not null default now(),
  unique(voter_id, project_id)   -- one vote per user per project
);

create index if not exists votes_project_idx on votes(project_id);
create index if not exists votes_voter_idx on votes(voter_id);

-- ── Updated-at trigger ─────────────────────────────────────
create or replace function update_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

create trigger users_updated_at before update on users
  for each row execute function update_updated_at();
create trigger hackathons_updated_at before update on hackathons
  for each row execute function update_updated_at();
create trigger projects_updated_at before update on projects
  for each row execute function update_updated_at();

-- ── RPC: increment vote count atomically ───────────────────
create or replace function increment_vote_count(p_project_id uuid, p_weight float)
returns void language plpgsql security definer as $$
begin
  update projects set vote_count = vote_count + p_weight where id = p_project_id;
end;
$$;

-- ── RPC: leaderboard ───────────────────────────────────────
create or replace function get_leaderboard(p_hackathon_id uuid)
returns table (
  rank            bigint,
  project_id      uuid,
  project_name    text,
  team_lead_id    uuid,
  demo_url        text,
  repo_url        text,
  tech_stack      text[],
  status          project_status,
  total_votes     float,
  unique_voters   bigint
) language sql security definer as $$
  select
    row_number() over (order by p.vote_count desc) as rank,
    p.id,
    p.name,
    p.team_lead_id,
    p.demo_url,
    p.repo_url,
    p.tech_stack,
    p.status,
    p.vote_count,
    count(v.id) as unique_voters
  from projects p
  left join votes v on v.project_id = p.id
  where p.hackathon_id = p_hackathon_id
  group by p.id
  order by p.vote_count desc;
$$;

-- ── Row Level Security ─────────────────────────────────────
alter table users enable row level security;
alter table hackathons enable row level security;
alter table projects enable row level security;
alter table votes enable row level security;

-- Users: anyone can read; only the owner or service role can write
create policy "users_public_read" on users for select using (true);
create policy "users_self_update" on users for update using (auth.uid()::text = id::text);

-- Hackathons: public read; only organizer can update
create policy "hackathons_public_read" on hackathons for select using (true);
create policy "hackathons_organizer_insert" on hackathons for insert with check (auth.uid()::text = organizer_id::text);
create policy "hackathons_organizer_update" on hackathons for update using (auth.uid()::text = organizer_id::text);

-- Projects: public read; team lead can insert/update their own
create policy "projects_public_read" on projects for select using (true);
create policy "projects_team_lead_insert" on projects for insert with check (auth.uid()::text = team_lead_id::text);
create policy "projects_team_lead_update" on projects for update using (auth.uid()::text = team_lead_id::text);

-- Votes: public read; authenticated users insert via service role (backend enforces genesis check)
create policy "votes_public_read" on votes for select using (true);

-- ── Storage bucket ─────────────────────────────────────────
insert into storage.buckets (id, name, public) values ('project-assets', 'project-assets', true)
on conflict do nothing;

create policy "project_assets_public_read" on storage.objects for select
  using (bucket_id = 'project-assets');
create policy "project_assets_auth_insert" on storage.objects for insert
  with check (bucket_id = 'project-assets' and auth.role() = 'authenticated');
