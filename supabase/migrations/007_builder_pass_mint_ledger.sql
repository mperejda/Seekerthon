-- Builder Pass mint ledger. Writes are performed by the backend service role.

alter table users
  add column if not exists has_builder_pass boolean not null default false;

create table if not exists builder_pass_mints (
  id                            uuid primary key default gen_random_uuid(),
  user_id                       uuid not null references users(id) on delete cascade,
  wallet_address                text not null,
  mint_pubkey                   text not null,
  mint_tx_signature             text not null,
  price_usdc_raw                bigint not null,
  treasury_usdc_received_raw    bigint not null,
  status                        text not null check (status in ('confirmed', 'reconciled_error')),
  raw_transaction_json          jsonb not null,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now(),
  unique (mint_pubkey),
  unique (mint_tx_signature)
);

create index if not exists builder_pass_mints_user_idx on builder_pass_mints(user_id);
create index if not exists builder_pass_mints_wallet_idx on builder_pass_mints(wallet_address);
create index if not exists builder_pass_mints_created_idx on builder_pass_mints(created_at desc);

drop trigger if exists builder_pass_mints_updated_at on builder_pass_mints;
create trigger builder_pass_mints_updated_at before update on builder_pass_mints
  for each row execute function update_updated_at();

alter table builder_pass_mints enable row level security;
-- No public write policies. Service role bypasses RLS for backend ledger writes.
