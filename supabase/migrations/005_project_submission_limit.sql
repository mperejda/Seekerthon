-- Launch limit: each hackathon can receive at most 100 project submissions.
-- This can be relaxed or replaced later by changing this trigger and API constant.
create or replace function enforce_project_submission_limit()
returns trigger language plpgsql as $$
begin
  perform pg_advisory_xact_lock(hashtext('projects_submission_limit_' || new.hackathon_id::text));

  if (
    select count(*)
    from projects
    where hackathon_id = new.hackathon_id
  ) >= 100 then
    raise exception 'Hackathon has reached the maximum of 100 projects'
      using errcode = '23505';
  end if;

  return new;
end;
$$;

drop trigger if exists projects_submission_limit_guard on projects;
create trigger projects_submission_limit_guard
  before insert on projects
  for each row
  execute function enforce_project_submission_limit();

update hackathons
set max_projects = 100
where max_projects > 100;

alter table hackathons
  drop constraint if exists hackathons_max_projects_launch_limit;

alter table hackathons
  add constraint hackathons_max_projects_launch_limit
  check (max_projects <= 100);
