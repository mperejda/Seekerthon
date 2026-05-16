-- Track backend SOL spend and SOL/USD quote for Builder Pass mints.

alter table builder_pass_mints
  add column if not exists mint_sol_spent_lamports bigint,
  add column if not exists sol_usd_price_at_mint numeric(20, 8),
  add column if not exists sol_usd_price_source text,
  add column if not exists sol_usd_price_checked_at timestamptz;
