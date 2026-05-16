-- Short-lived pending Builder Pass mint transactions.
-- The backend stores encrypted mint signer material between /prepare and /claim.

create table if not exists builder_pass_pending_mints (
  id                              uuid primary key default gen_random_uuid(),
  mint_pubkey                     text not null unique,
  buyer_wallet                    text not null,
  message_b64                     text not null,
  recent_blockhash                text not null,
  encrypted_mint_keypair          text not null,
  expires_at                      timestamptz not null,
  created_at                      timestamptz not null default now()
);

create index if not exists builder_pass_pending_mints_buyer_idx
  on builder_pass_pending_mints(buyer_wallet);

create index if not exists builder_pass_pending_mints_expires_idx
  on builder_pass_pending_mints(expires_at);

alter table builder_pass_pending_mints enable row level security;
-- No public policies. Backend service role is the only writer/reader.
