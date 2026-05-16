-- Store the USD value of backend SOL spent on Builder Pass mints.

alter table builder_pass_mints
  add column if not exists mint_sol_spent_usd numeric(20, 8);
