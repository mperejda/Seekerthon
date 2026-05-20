-- A given FCM token can only ever belong to one user. If a different user
-- registers the same token (e.g. after device reassignment) the new user_id
-- overwrites the old row so the previous owner no longer receives that
-- device's push notifications.

alter table device_tokens
  drop constraint if exists device_tokens_user_id_token_key;

-- Collapse any pre-existing duplicate (token) rows, keeping the most recent.
delete from device_tokens d
using device_tokens d2
where d.token = d2.token
  and d.created_at < d2.created_at;

alter table device_tokens
  add constraint device_tokens_token_key unique (token);
