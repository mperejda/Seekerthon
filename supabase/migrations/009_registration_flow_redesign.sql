-- Registration now triggers the on-chain register_project TX immediately.
-- Projects start as 'registered' (on-chain PDA exists, is_submitted=false on-chain)
-- and advance to 'submitted' when the team fills in details + mark_submitted is confirmed.
--
-- The escrow contract enforces three conditions for prize eligibility:
--   1. ProjectRecord PDA exists  (allowlist — set at registration)
--   2. project_record.is_submitted == true  (set by mark_submitted instruction)
--   3. Platform admin claim certificate  (winner — issued by backend for top submitted project)
--
-- The organizer refund is gated on submitted_project_count == 0 (on-chain), so
-- registered-but-not-submitted projects do not block the refund.

-- New project status for the registered-but-not-yet-submitted state.
alter type project_status add value if not exists 'registered';

-- Link each hackathon registration to its corresponding project stub.
alter table hackathon_registrations
  add column if not exists project_id uuid references projects(id);

-- Allow name to be empty at registration time; the submit step validates it.
alter table projects alter column name set default '';
