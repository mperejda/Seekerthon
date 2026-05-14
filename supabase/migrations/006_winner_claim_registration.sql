-- Project submissions now require a confirmed on-chain ProjectRecord before
-- they become votable or eligible for prize claiming.
alter type project_status add value if not exists 'pending_registration';

-- Hide pending registrations from leaderboard/voting surfaces.
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
    and p.status in ('submitted', 'approved', 'winner')
    and p.onchain_pda is not null
  group by p.id
  order by p.vote_count desc;
$$;
