-- Track the buyer payment signature explicitly so claim_builder_pass is
-- idempotent: if the on-chain mint lands but the DB ledger insert fails, a
-- retry with the same payment signature must NOT double-mint.

alter table builder_pass_mints
  add column if not exists payment_tx_signature text;

-- Backfill from raw_transaction_json where possible.
update builder_pass_mints
set payment_tx_signature = raw_transaction_json->>'payment_tx_signature'
where payment_tx_signature is null
  and raw_transaction_json ? 'payment_tx_signature';

create unique index if not exists builder_pass_mints_payment_sig_key
  on builder_pass_mints(payment_tx_signature)
  where payment_tx_signature is not null;
