-- Atomically insert a vote and update the denormalized project tally.
-- This prevents votes.project_id rows and projects.vote_count from diverging
-- if the API process fails between two separate database calls.

create or replace function record_vote(
  p_voter_id uuid,
  p_project_id uuid,
  p_weight float,
  p_tx_signature text
)
returns votes
language plpgsql
security definer
set search_path = public
as $$
declare
  inserted_vote votes;
begin
  insert into votes (voter_id, project_id, weight, tx_signature)
  values (p_voter_id, p_project_id, p_weight, p_tx_signature)
  returning * into inserted_vote;

  update projects
  set vote_count = vote_count + p_weight
  where id = p_project_id;

  return inserted_vote;
end;
$$;

revoke all on function record_vote(uuid, uuid, float, text) from public, anon, authenticated;
grant execute on function record_vote(uuid, uuid, float, text) to service_role;

-- The backend no longer uses this direct tally mutator for vote confirmation.
-- Keep it service-only so clients cannot inflate project totals through PostgREST.
revoke all on function increment_vote_count(uuid, float) from public, anon, authenticated;
grant execute on function increment_vote_count(uuid, float) to service_role;
