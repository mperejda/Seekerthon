-- Allow only one non-completed hackathon at a time.
-- This covers draft, open, voting, and verifying hackathons globally.
--
-- A partial unique index cannot be added if historical data already contains
-- multiple active hackathons. This trigger installs cleanly in that state, still
-- allows organizers to mark old hackathons completed, and blocks new active
-- rows until only one active hackathon remains.
create or replace function enforce_single_active_hackathon()
returns trigger language plpgsql as $$
begin
  if new.status = 'completed' then
    return new;
  end if;

  perform pg_advisory_xact_lock(hashtext('hackathons_single_active'));

  if exists (
    select 1
    from hackathons
    where status <> 'completed'
      and id <> new.id
  ) then
    raise exception 'A hackathon is already active. Complete it before creating a new one.'
      using errcode = '23505';
  end if;

  return new;
end;
$$;

drop trigger if exists hackathons_single_active_guard on hackathons;
create trigger hackathons_single_active_guard
  before insert or update of status on hackathons
  for each row
  execute function enforce_single_active_hackathon();
