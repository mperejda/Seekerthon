-- Migration 003: rename prize_pool_lamports → prize_pool_usdc (USDC base units, 6 decimals)

alter table hackathons
  rename column prize_pool_lamports to prize_pool_usdc;

-- Change from bigint (lamports) to numeric to hold USDC base units (still integer-safe as bigint,
-- but numeric gives flexibility for display queries)
alter table hackathons
  alter column prize_pool_usdc type numeric using prize_pool_usdc::numeric;
