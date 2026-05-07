# Seekerthon Solana — Build / Test / Deploy Runbook

## Version pins (do not change without reading the compatibility note at the bottom)

| Component | Version |
|---|---|
| Rust nightly | `nightly-2024-12-15` |
| Anchor | `0.30.1` |
| Solana CLI | `1.18.26` |
| proc-macro2 | `1.0.91` (Cargo.lock) |

---

## Prerequisites (host machine, one-time)

1. **Docker Desktop** installed and running (BuildKit enabled by default in v23+).
2. **Solana keypair** at `~/.config/solana/id.json`.  
   If you don't have one: `solana-keygen new --outfile ~/.config/solana/id.json`

---

## 1 — Build the Docker image

Run from the `solana/` directory.

```bash
cd solana/
docker compose build
```

This installs Rust nightly-2024-12-15, Solana CLI 1.18.26, Node 20, yarn,
and anchor-cli 0.30.1 into the image. Expect 10-20 min on a cold cache;
subsequent builds use Docker layer cache and finish in under a minute.

**Verify:**
```bash
docker compose run --rm anchor anchor --version
# expected: anchor-cli 0.30.1
docker compose run --rm anchor solana --version
# expected: solana-cli 1.18.26
```

---

## 2 — Build the programs

```bash
docker compose run --rm anchor anchor build
```

Output artifacts:
- `target/deploy/voting.so`
- `target/deploy/escrow.so`
- `target/idl/voting.json`
- `target/idl/escrow.json`
- `target/types/voting.ts`
- `target/types/escrow.ts`

First run downloads ~500 MB of crates into the `cargo-registry` Docker volume.
Subsequent runs are incremental (seconds to minutes depending on changes).

---

## 3 — Run the tests

Tests require the programs to be built first (step 2) so that IDL/types exist.

```bash
docker compose run --rm anchor bash -c "yarn install && anchor test --skip-build"
```

`--skip-build` prevents a redundant recompile since you just built.  
Without `--skip-build` anchor will rebuild before testing (safe but slower).

Expected: **20 tests passing** (7 voting, 13 escrow).

---

## 4 — Deploy to devnet

Ensure your keypair has at least 2 SOL on devnet. The script will airdrop
if the balance is low but devnet airdrops are rate-limited and unreliable.

```bash
# Fund manually if needed (do this on the host, not in Docker):
solana airdrop 2 --url devnet

# Deploy:
docker compose run --rm anchor ./deploy-devnet.sh
```

The script:
1. Checks/generates the keypair
2. Airdrops if balance < 2 SOL (retries 3x)
3. Runs `anchor build`
4. Deploys both programs to devnet
5. Patches `../backend/.env` with the new program IDs

To target a different RPC endpoint:
```bash
SOLANA_RPC=https://my-rpc.example.com docker compose run --rm anchor ./deploy-devnet.sh
```

---

## Troubleshooting

### "toolchain 'nightly-2024-12-15' is not installed" at anchor build time

The Docker image was built with a different nightly. Rebuild the image:
```bash
docker compose build --no-cache
```

### "proc_macro::SourceFile not found" or "source_file method not found"

The Cargo.lock has been modified by a failed build and now pins
proc-macro2 to an incompatible version. Restore it:

```bash
# Inside the container or on the host in solana/:
git checkout Cargo.lock
```

Then retry `anchor build`.

### Build hangs / OOM on large machines

Limit parallelism:
```bash
docker compose run --rm anchor bash -c "anchor build -- -j 2"
```

### "insufficient funds" during deploy

The deploy script auto-airdrops but devnet airdrops fail intermittently.
Fund manually on the host:
```bash
solana airdrop 2 --url devnet
solana balance --url devnet
```

### Stale Docker volumes (weird cache errors)

Nuke the named volumes and start fresh — this only affects cached build
artifacts, not your source code:
```bash
docker compose down -v
docker compose build
```

### anchor test: "Cannot find module '../target/types/voting'"

Run `anchor build` first to generate the TypeScript types.

---

## Compatibility note — why these exact versions

Anchor 0.30.1 uses `anchor-syn 0.30.1` which calls
`proc_macro2::Span::source_file()`. That method was removed in
proc-macro2 v1.0.92. proc-macro2 v1.0.91 (Cargo.lock) still has it, but
v1.0.91 in turn calls `proc_macro::SourceFile` — a nightly-only API that
was removed from Rust nightly on 2025-01-08.

The only nightly range that satisfies both constraints is before 2025-01-08.
`nightly-2024-12-15` is the pinned safe point.

**To upgrade Anchor** (e.g. to 0.31+), update all four things together:
Dockerfile `ANCHOR_VERSION`, `rust-toolchain.toml` channel,
`Cargo.toml` anchor-lang/anchor-spl versions, and delete `Cargo.lock`
so it re-resolves cleanly.
