-- Store the USD display value for registration fees collected in USDC.

alter table registration_fees
  add column if not exists amount_usd numeric(20, 6);
