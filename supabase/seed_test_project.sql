-- ============================================================
-- Seed: multiple test projects for hackathon 5c052491-8a2d-402f-8621-101916c491e6
-- Run this in the Supabase SQL editor (service role bypasses RLS).
-- Each project needs a distinct team_lead (wallet_address) due to the
-- unique constraint on (hackathon_id, team_lead_id).
-- ============================================================

do $$
declare
  v_hackathon_id uuid := '5c052491-8a2d-402f-8621-101916c491e6';

  type project_rec is record (
    wallet  text,
    name    text,
    desc    text,
    demo    text,
    repo    text,
    stack   text[]
  );

  projects project_rec[] := array[
    ('TestWallet1111111111111111111111111111111111',
     'Seeker Analytics Dashboard',
     'Real-time on-chain analytics for Seeker Genesis NFT holders, showing holder activity, vote trends, and prize pool history.',
     'https://www.youtube.com/watch?v=P-QDswte3ug',
     'https://github.com/mperejda/Seekerthon',
     array['Solana', 'TypeScript', 'React', 'Supabase']),

    ('TestWallet2222222222222222222222222222222222',
     'NFT Governance Toolkit',
     'A governance framework letting any NFT collection bootstrap on-chain voting with weighted votes based on staked tokens.',
     'https://www.youtube.com/watch?v=P-QDswte3ug',
     'https://github.com/mperejda/Seekerthon',
     array['Solana', 'Rust', 'Anchor']),

    ('TestWallet3333333333333333333333333333333333',
     'Seekerthon Mobile Wallet',
     'An open-source reference wallet for the Seeker device with MWA signing, portfolio view, and hackathon feed built-in.',
     'https://www.youtube.com/watch?v=P-QDswte3ug',
     'https://github.com/mperejda/Seekerthon',
     array['Kotlin', 'Jetpack Compose', 'Mobile Wallet Adapter']),

    ('TestWallet4444444444444444444444444444444444',
     'Decentralised Bounty Board',
     'Post and claim bounties funded by USDC escrow on Solana. Verified completion unlocks payout without a trusted third party.',
     'https://www.youtube.com/watch?v=P-QDswte3ug',
     'https://github.com/mperejda/Seekerthon',
     array['Solana', 'Rust', 'Next.js', 'Token-2022']),

    ('TestWallet5555555555555555555555555555555555',
     'Seeker Social Graph',
     'On-chain social graph for Seeker Genesis holders — follow, endorse skills, and discover collaborators for future hackathons.',
     'https://www.youtube.com/watch?v=P-QDswte3ug',
     'https://github.com/mperejda/Seekerthon',
     array['Solana', 'Rust', 'React', 'GraphQL'])
  ];

  p project_rec;
  v_user_id uuid;
  v_project_id uuid;
begin
  foreach p in array projects loop
    -- Upsert team-lead user
    insert into users (wallet_address, skr_balance, skr_staked, vote_multiplier, is_seeker_verified)
    values (p.wallet, 1000, 500, 1.0, false)
    on conflict (wallet_address) do nothing;

    select id into v_user_id from users where wallet_address = p.wallet;

    v_project_id := gen_random_uuid();

    insert into projects (
      id, hackathon_id, team_lead_id, name, description,
      demo_url, repo_url, tech_stack, status
    )
    values (
      v_project_id, v_hackathon_id, v_user_id, p.name, p.desc,
      p.demo, p.repo, p.stack, 'submitted'
    )
    on conflict (hackathon_id, team_lead_id) do nothing;

    raise notice 'Project: % | user=% project=%', p.name, v_user_id, v_project_id;
  end loop;
end;
$$;
