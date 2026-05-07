-- ============================================================
-- Seed: multiple test projects for hackathon 5c052491-8a2d-402f-8621-101916c491e6
-- Run this in the Supabase SQL editor (service role bypasses RLS).
-- Each project needs a distinct team_lead (wallet_address) due to the
-- unique constraint on (hackathon_id, team_lead_id).
-- ============================================================

do $$
declare
  v_hackathon_id uuid := '5c052491-8a2d-402f-8621-101916c491e6';
  v_user_id      uuid;
begin

  -- ── Project 1 ──────────────────────────────────────────────
  insert into users (wallet_address, skr_balance, skr_staked, vote_multiplier, is_seeker_verified)
  values ('TestWallet1111111111111111111111111111111111', 1000, 500, 1.0, false)
  on conflict (wallet_address) do nothing;
  select id into v_user_id from users where wallet_address = 'TestWallet1111111111111111111111111111111111';
  insert into projects (id, hackathon_id, team_lead_id, name, description, demo_url, repo_url, tech_stack, status)
  values (gen_random_uuid(), v_hackathon_id, v_user_id,
    'Seeker Analytics Dashboard',
    'Real-time on-chain analytics for Seeker Genesis NFT holders, showing holder activity, vote trends, and prize pool history.',
    'https://www.youtube.com/watch?v=P-QDswte3ug',
    'https://github.com/mperejda/Seekerthon',
    array['Solana', 'TypeScript', 'React', 'Supabase'],
    'submitted')
  on conflict (hackathon_id, team_lead_id) do nothing;
  raise notice 'Project 1 done — user_id=%', v_user_id;

  -- ── Project 2 ──────────────────────────────────────────────
  insert into users (wallet_address, skr_balance, skr_staked, vote_multiplier, is_seeker_verified)
  values ('TestWallet2222222222222222222222222222222222', 1000, 500, 1.0, false)
  on conflict (wallet_address) do nothing;
  select id into v_user_id from users where wallet_address = 'TestWallet2222222222222222222222222222222222';
  insert into projects (id, hackathon_id, team_lead_id, name, description, demo_url, repo_url, tech_stack, status)
  values (gen_random_uuid(), v_hackathon_id, v_user_id,
    'NFT Governance Toolkit',
    'A governance framework letting any NFT collection bootstrap on-chain voting with weighted votes based on staked tokens.',
    'https://www.youtube.com/watch?v=P-QDswte3ug',
    'https://github.com/mperejda/Seekerthon',
    array['Solana', 'Rust', 'Anchor'],
    'submitted')
  on conflict (hackathon_id, team_lead_id) do nothing;
  raise notice 'Project 2 done — user_id=%', v_user_id;

  -- ── Project 3 ──────────────────────────────────────────────
  insert into users (wallet_address, skr_balance, skr_staked, vote_multiplier, is_seeker_verified)
  values ('TestWallet3333333333333333333333333333333333', 1000, 500, 1.0, false)
  on conflict (wallet_address) do nothing;
  select id into v_user_id from users where wallet_address = 'TestWallet3333333333333333333333333333333333';
  insert into projects (id, hackathon_id, team_lead_id, name, description, demo_url, repo_url, tech_stack, status)
  values (gen_random_uuid(), v_hackathon_id, v_user_id,
    'Seekerthon Mobile Wallet',
    'An open-source reference wallet for the Seeker device with MWA signing, portfolio view, and hackathon feed built-in.',
    'https://www.youtube.com/watch?v=P-QDswte3ug',
    'https://github.com/mperejda/Seekerthon',
    array['Kotlin', 'Jetpack Compose', 'Mobile Wallet Adapter'],
    'submitted')
  on conflict (hackathon_id, team_lead_id) do nothing;
  raise notice 'Project 3 done — user_id=%', v_user_id;

  -- ── Project 4 ──────────────────────────────────────────────
  insert into users (wallet_address, skr_balance, skr_staked, vote_multiplier, is_seeker_verified)
  values ('TestWallet4444444444444444444444444444444444', 1000, 500, 1.0, false)
  on conflict (wallet_address) do nothing;
  select id into v_user_id from users where wallet_address = 'TestWallet4444444444444444444444444444444444';
  insert into projects (id, hackathon_id, team_lead_id, name, description, demo_url, repo_url, tech_stack, status)
  values (gen_random_uuid(), v_hackathon_id, v_user_id,
    'Decentralised Bounty Board',
    'Post and claim bounties funded by USDC escrow on Solana. Verified completion unlocks payout without a trusted third party.',
    'https://www.youtube.com/watch?v=P-QDswte3ug',
    'https://github.com/mperejda/Seekerthon',
    array['Solana', 'Rust', 'Next.js', 'Token-2022'],
    'submitted')
  on conflict (hackathon_id, team_lead_id) do nothing;
  raise notice 'Project 4 done — user_id=%', v_user_id;

  -- ── Project 5 ──────────────────────────────────────────────
  insert into users (wallet_address, skr_balance, skr_staked, vote_multiplier, is_seeker_verified)
  values ('TestWallet5555555555555555555555555555555555', 1000, 500, 1.0, false)
  on conflict (wallet_address) do nothing;
  select id into v_user_id from users where wallet_address = 'TestWallet5555555555555555555555555555555555';
  insert into projects (id, hackathon_id, team_lead_id, name, description, demo_url, repo_url, tech_stack, status)
  values (gen_random_uuid(), v_hackathon_id, v_user_id,
    'Seeker Social Graph',
    'On-chain social graph for Seeker Genesis holders — follow, endorse skills, and discover collaborators for future hackathons.',
    'https://www.youtube.com/watch?v=P-QDswte3ug',
    'https://github.com/mperejda/Seekerthon',
    array['Solana', 'Rust', 'React', 'GraphQL'],
    'submitted')
  on conflict (hackathon_id, team_lead_id) do nothing;
  raise notice 'Project 5 done — user_id=%', v_user_id;

end;
$$;
