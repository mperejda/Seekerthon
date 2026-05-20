-- Bind login challenges to the wallet that requested them so a challenge
-- issued for wallet A cannot be spent by wallet B.

alter table challenges
  add column if not exists wallet_address text;

create index if not exists challenges_wallet_idx on challenges(wallet_address);
