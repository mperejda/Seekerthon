-- ============================================================
-- Seed: test project for hackathon 5c052491-8a2d-402f-8621-101916c491e6
-- Run this in the Supabase SQL editor (service role bypasses RLS).
-- ============================================================

do $$
declare
  v_user_id    uuid;
  v_project_id uuid := gen_random_uuid();
  v_hackathon_id uuid := '5c052491-8a2d-402f-8621-101916c491e6';
begin

  -- 1. Upsert a test team-lead user
  insert into users (wallet_address, skr_balance, skr_staked, vote_multiplier, is_seeker_verified)
  values ('TestWallet1111111111111111111111111111111111', 1000, 0, 1.0, false)
  on conflict (wallet_address) do nothing;

  select id into v_user_id
  from users
  where wallet_address = 'TestWallet1111111111111111111111111111111111';

  -- 2. Insert the test project (skip if already exists for this team lead)
  insert into projects (
    id,
    hackathon_id,
    team_lead_id,
    name,
    description,
    demo_url,
    repo_url,
    tech_stack,
    status
  )
  values (
    v_project_id,
    v_hackathon_id,
    v_user_id,
    'Test Project Alpha',
    'A test project created for QA purposes.',
    'https://demo.example.com',
    'https://github.com/mperejda/Seekerthon',
    array['Solana', 'Rust', 'React'],
    'submitted'
  )
  on conflict (hackathon_id, team_lead_id) do nothing;

  raise notice 'Done — user_id=%, project_id=%', v_user_id, v_project_id;
end;
$$;
