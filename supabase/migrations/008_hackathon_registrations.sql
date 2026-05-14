-- Participants register to reserve a spot before submitting their project.
-- Max 100 registrations per hackathon (enforced by DB trigger + API).

create table if not exists hackathon_registrations (
  id              uuid primary key default gen_random_uuid(),
  hackathon_id    uuid not null references hackathons(id) on delete cascade,
  user_id         uuid not null references users(id),
  wallet_address  text not null,
  registered_at   timestamptz not null default now(),
  unique(hackathon_id, user_id)
);

create index if not exists registrations_hackathon_idx on hackathon_registrations(hackathon_id);
create index if not exists registrations_user_idx on hackathon_registrations(user_id);

-- Advisory-lock-guarded trigger prevents overselling the 100 spots under concurrent load.
create or replace function enforce_hackathon_registration_limit()
returns trigger language plpgsql as $$
begin
  perform pg_advisory_xact_lock(hashtext('reg_limit_' || new.hackathon_id::text));

  if (
    select count(*)
    from hackathon_registrations
    where hackathon_id = new.hackathon_id
  ) >= 100 then
    raise exception 'Hackathon registration is full (100 spots)'
      using errcode = '23505';
  end if;

  return new;
end;
$$;

create trigger hackathon_registration_limit_guard
  before insert on hackathon_registrations
  for each row
  execute function enforce_hackathon_registration_limit();

-- RLS
alter table hackathon_registrations enable row level security;
create policy "registrations_public_read" on hackathon_registrations for select using (true);
