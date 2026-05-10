// Run `anchor build` before `anchor test` to generate target/idl/escrow.json.
import * as anchor from "@coral-xyz/anchor";
import {
  Keypair,
  PublicKey,
  LAMPORTS_PER_SOL,
  SystemProgram,
  SYSVAR_RENT_PUBKEY,
} from "@solana/web3.js";
import {
  createMint,
  createAssociatedTokenAccount,
  getAssociatedTokenAddress,
  mintTo,
  getAccount,
  TOKEN_PROGRAM_ID,
  ASSOCIATED_TOKEN_PROGRAM_ID,
} from "@solana/spl-token";
import { assert } from "chai";

describe("escrow", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const program = anchor.workspace.Escrow as any;
  const payer = (provider.wallet as anchor.Wallet).payer;

  // Shared token infrastructure
  let usdcMint: PublicKey;
  let mintAuthority: Keypair;

  // ── Helpers ────────────────────────────────────────────────────────────────

  async function fund(pubkey: PublicKey, sol = 2): Promise<void> {
    const sig = await provider.connection.requestAirdrop(
      pubkey,
      sol * LAMPORTS_PER_SOL
    );
    const latest = await provider.connection.getLatestBlockhash();
    await provider.connection.confirmTransaction({ signature: sig, ...latest });
  }

  /** 16-byte hackathon ID drawn from random keypair bytes */
  function randomHackathonId(): number[] {
    return Array.from(Keypair.generate().publicKey.toBuffer().subarray(0, 16));
  }

  function findEscrowPda(hackathonId: number[]): PublicKey {
    const [pda] = PublicKey.findProgramAddressSync(
      [Buffer.from("hackathon_escrow"), Buffer.from(hackathonId)],
      program.programId
    );
    return pda;
  }

  /** Create an organizer, fund it, give it a USDC ATA with `usdcAmount` base units. */
  async function setupOrganizer(usdcAmount: number): Promise<{
    organizer: Keypair;
    organizerAta: PublicKey;
  }> {
    const organizer = Keypair.generate();
    await fund(organizer.publicKey, 3);

    const organizerAta = await createAssociatedTokenAccount(
      provider.connection,
      payer,
      usdcMint,
      organizer.publicKey
    );
    await mintTo(
      provider.connection,
      payer,
      usdcMint,
      organizerAta,
      mintAuthority,
      usdcAmount
    );
    return { organizer, organizerAta };
  }

  /** Create a winner keypair with a funded USDC ATA. */
  async function setupWinner(): Promise<{
    winner: Keypair;
    winnerAta: PublicKey;
  }> {
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(
      provider.connection,
      payer,
      usdcMint,
      winner.publicKey
    );
    return { winner, winnerAta };
  }

  /**
   * Create a hackathon escrow and deposit prize USDC.
   * Returns the escrow PDA and vault ATA.
   */
  async function createHackathon(opts: {
    organizer: Keypair;
    organizerAta: PublicKey;
    hackathonId: number[];
    prizeUsdc: number;
    votingStart: anchor.BN;
    votingEnd: anchor.BN;
  }): Promise<{ escrowPda: PublicKey; vault: PublicKey }> {
    const escrowPda = findEscrowPda(opts.hackathonId);
    const vault = await getAssociatedTokenAddress(
      usdcMint,
      escrowPda,
      true // allowOwnerOffCurve — PDAs are off-curve
    );

    await program.methods
      .createHackathon(
        opts.hackathonId,
        new anchor.BN(opts.prizeUsdc),
        opts.votingStart,
        opts.votingEnd
      )
      .accounts({
        organizer: opts.organizer.publicKey,
        usdcMint,
        hackathonEscrow: escrowPda,
        vault,
        organizerUsdcAta: opts.organizerAta,
        tokenProgram: TOKEN_PROGRAM_ID,
        associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .signers([opts.organizer])
      .rpc();

    return { escrowPda, vault };
  }

  async function expectError(fn: () => Promise<unknown>, fragment: string): Promise<void> {
    try {
      await fn();
      assert.fail(`Expected error containing "${fragment}" but transaction succeeded`);
    } catch (err: unknown) {
      const msg = String(err);
      if (msg.includes("Expected error containing")) throw err;
      assert.include(msg, fragment, `Wrong error — got: ${msg}`);
    }
  }

  // ── Setup ──────────────────────────────────────────────────────────────────

  before(async () => {
    mintAuthority = Keypair.generate();
    await fund(mintAuthority.publicKey);

    usdcMint = await createMint(
      provider.connection,
      payer,
      mintAuthority.publicKey,
      null, // no freeze authority
      6    // 6 decimals, matching USDC
    );
  });

  // ── create_hackathon ───────────────────────────────────────────────────────

  it("creates a hackathon and deposits USDC into the vault", async () => {
    const { organizer, organizerAta } = await setupOrganizer(100_000_000); // 100 USDC
    const hackathonId = randomHackathonId();
    const now = Math.floor(Date.now() / 1000);

    const { escrowPda, vault } = await createHackathon({
      organizer,
      organizerAta,
      hackathonId,
      prizeUsdc: 100_000_000,
      votingStart: new anchor.BN(now + 3600),
      votingEnd: new anchor.BN(now + 7200),
    });

    const escrow = await program.account.hackathonEscrow.fetch(escrowPda);
    assert.equal(escrow.prizeUsdc.toNumber(), 100_000_000);
    assert.equal(escrow.organizer.toBase58(), organizer.publicKey.toBase58());
    assert.deepEqual(escrow.status, { active: {} });

    const vaultAcct = await getAccount(provider.connection, vault);
    assert.equal(Number(vaultAcct.amount), 100_000_000);

    const orgAcct = await getAccount(provider.connection, organizerAta);
    assert.equal(Number(orgAcct.amount), 0); // all transferred out
  });

  it("rejects zero prize", async () => {
    const { organizer, organizerAta } = await setupOrganizer(0);
    const hackathonId = randomHackathonId();
    const now = Math.floor(Date.now() / 1000);
    const escrowPda = findEscrowPda(hackathonId);
    const vault = await getAssociatedTokenAddress(usdcMint, escrowPda, true);

    await expectError(
      () =>
        program.methods
          .createHackathon(
            hackathonId,
            new anchor.BN(0),
            new anchor.BN(now + 3600),
            new anchor.BN(now + 7200)
          )
          .accounts({
            organizer: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrowPda,
            vault,
            organizerUsdcAta: organizerAta,
            tokenProgram: TOKEN_PROGRAM_ID,
            associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            systemProgram: SystemProgram.programId,
            rent: SYSVAR_RENT_PUBKEY,
          })
          .signers([organizer])
          .rpc(),
      "InvalidPrize"
    );
  });

  it("rejects voting_end <= voting_start", async () => {
    const { organizer, organizerAta } = await setupOrganizer(1_000_000);
    const hackathonId = randomHackathonId();
    const now = Math.floor(Date.now() / 1000);
    const escrowPda = findEscrowPda(hackathonId);
    const vault = await getAssociatedTokenAddress(usdcMint, escrowPda, true);

    await expectError(
      () =>
        program.methods
          .createHackathon(
            hackathonId,
            new anchor.BN(1_000_000),
            new anchor.BN(now + 7200), // start > end
            new anchor.BN(now + 3600)
          )
          .accounts({
            organizer: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrowPda,
            vault,
            organizerUsdcAta: organizerAta,
            tokenProgram: TOKEN_PROGRAM_ID,
            associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            systemProgram: SystemProgram.programId,
            rent: SYSVAR_RENT_PUBKEY,
          })
          .signers([organizer])
          .rpc(),
      "InvalidTimestamps"
    );
  });

  it("rejects negative voting_start", async () => {
    const { organizer, organizerAta } = await setupOrganizer(1_000_000);
    const hackathonId = randomHackathonId();
    const escrowPda = findEscrowPda(hackathonId);
    const vault = await getAssociatedTokenAddress(usdcMint, escrowPda, true);

    await expectError(
      () =>
        program.methods
          .createHackathon(
            hackathonId,
            new anchor.BN(1_000_000),
            new anchor.BN(-1),
            new anchor.BN(9999999999)
          )
          .accounts({
            organizer: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrowPda,
            vault,
            organizerUsdcAta: organizerAta,
            tokenProgram: TOKEN_PROGRAM_ID,
            associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            systemProgram: SystemProgram.programId,
            rent: SYSVAR_RENT_PUBKEY,
          })
          .signers([organizer])
          .rpc(),
      "InvalidTimestamps"
    );
  });

  it("rejects voting_start equal to voting_end", async () => {
    const { organizer, organizerAta } = await setupOrganizer(1_000_000);
    const hackathonId = randomHackathonId();
    const now = Math.floor(Date.now() / 1000);
    const escrowPda = findEscrowPda(hackathonId);
    const vault = await getAssociatedTokenAddress(usdcMint, escrowPda, true);

    await expectError(
      () =>
        program.methods
          .createHackathon(
            hackathonId,
            new anchor.BN(1_000_000),
            new anchor.BN(now + 3600),
            new anchor.BN(now + 3600) // equal, not strictly greater
          )
          .accounts({
            organizer: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrowPda,
            vault,
            organizerUsdcAta: organizerAta,
            tokenProgram: TOKEN_PROGRAM_ID,
            associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            systemProgram: SystemProgram.programId,
            rent: SYSVAR_RENT_PUBKEY,
          })
          .signers([organizer])
          .rpc(),
      "InvalidTimestamps"
    );
  });

  it("rejects duplicate hackathon ID", async () => {
    const { organizer, organizerAta } = await setupOrganizer(200_000_000);
    const hackathonId = randomHackathonId();
    const now = Math.floor(Date.now() / 1000);
    const escrowPda = findEscrowPda(hackathonId);
    const vault = await getAssociatedTokenAddress(usdcMint, escrowPda, true);

    await createHackathon({
      organizer,
      organizerAta,
      hackathonId,
      prizeUsdc: 100_000_000,
      votingStart: new anchor.BN(now + 3600),
      votingEnd: new anchor.BN(now + 7200),
    });

    // Second create_hackathon with the same ID must fail — PDA already initialised
    await expectError(
      () =>
        program.methods
          .createHackathon(
            hackathonId,
            new anchor.BN(100_000_000),
            new anchor.BN(now + 3600),
            new anchor.BN(now + 7200)
          )
          .accounts({
            organizer: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrowPda,
            vault,
            organizerUsdcAta: organizerAta,
            tokenProgram: TOKEN_PROGRAM_ID,
            associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
            systemProgram: SystemProgram.programId,
            rent: SYSVAR_RENT_PUBKEY,
          })
          .signers([organizer])
          .rpc(),
      "already in use"
    );
  });

  // ── release_prize ──────────────────────────────────────────────────────────

  describe("release_prize", () => {
    let organizer: Keypair;
    let organizerAta: PublicKey;
    let escrowPda: PublicKey;
    let vault: PublicKey;
    let hackathonId: number[];

    const PRIZE = 100_000_000; // 100 USDC

    // Voting window already ended — release_prize should succeed
    before(async () => {
      ({ organizer, organizerAta } = await setupOrganizer(PRIZE));
      hackathonId = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);

      ({ escrowPda, vault } = await createHackathon({
        organizer,
        organizerAta,
        hackathonId,
        prizeUsdc: PRIZE,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      }));
    });

    it("distributes USDC to winners according to share bps", async () => {
      const { winnerAta: w1Ata } = await setupWinner();
      const { winnerAta: w2Ata } = await setupWinner();

      // w1 gets 60%, w2 gets 40%
      await program.methods
        .releasePrize(hackathonId, [6_000, 4_000])
        .accounts({
          organizer: organizer.publicKey,
          usdcMint,
          hackathonEscrow: escrowPda,
          vault,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .remainingAccounts([
          { pubkey: w1Ata, isSigner: false, isWritable: true },
          { pubkey: w2Ata, isSigner: false, isWritable: true },
        ])
        .signers([organizer])
        .rpc();

      const w1 = await getAccount(provider.connection, w1Ata);
      const w2 = await getAccount(provider.connection, w2Ata);
      assert.equal(Number(w1.amount), 60_000_000); // 60% of 100 USDC
      assert.equal(Number(w2.amount), 40_000_000); // 40% of 100 USDC

      const escrow = await program.account.hackathonEscrow.fetch(escrowPda);
      assert.deepEqual(escrow.status, { released: {} });
    });

    it("rejects release before voting_end has passed", async () => {
      const { organizer: org, organizerAta: ata } = await setupOrganizer(1_000_000);
      const hId = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep, vault: v } = await createHackathon({
        organizer: org,
        organizerAta: ata,
        hackathonId: hId,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now + 100),
        votingEnd: new anchor.BN(now + 200),
      });
      const { winnerAta } = await setupWinner();

      await expectError(
        () =>
          program.methods
            .releasePrize(hId, [10_000])
            .accounts({
              organizer: org.publicKey,
              usdcMint,
              hackathonEscrow: ep,
              vault: v,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: winnerAta, isSigner: false, isWritable: true },
            ])
            .signers([org])
            .rpc(),
        "VotingNotEnded"
      );
    });

    it("rejects a non-organizer caller", async () => {
      const { organizer: org2, organizerAta: ata2 } = await setupOrganizer(1_000_000);
      const hId2 = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep2, vault: v2 } = await createHackathon({
        organizer: org2,
        organizerAta: ata2,
        hackathonId: hId2,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });

      const attacker = Keypair.generate();
      await fund(attacker.publicKey);
      const { winnerAta } = await setupWinner();

      await expectError(
        () =>
          program.methods
            .releasePrize(hId2, [10_000])
            .accounts({
              organizer: attacker.publicKey,
              usdcMint,
              hackathonEscrow: ep2,
              vault: v2,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: winnerAta, isSigner: false, isWritable: true },
            ])
            .signers([attacker])
            .rpc(),
        "NotOrganizer"
      );
    });

    it("rejects shares summing to > 100% (> 10_000 bps)", async () => {
      const { organizer: org3, organizerAta: ata3 } = await setupOrganizer(1_000_000);
      const hId3 = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep3, vault: v3 } = await createHackathon({
        organizer: org3,
        organizerAta: ata3,
        hackathonId: hId3,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });
      const { winnerAta } = await setupWinner();

      await expectError(
        () =>
          program.methods
            .releasePrize(hId3, [10_001])
            .accounts({
              organizer: org3.publicKey,
              usdcMint,
              hackathonEscrow: ep3,
              vault: v3,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: winnerAta, isSigner: false, isWritable: true },
            ])
            .signers([org3])
            .rpc(),
        "InvalidShares"
      );
    });

    it("rejects recipient count != share count", async () => {
      const { organizer: org4, organizerAta: ata4 } = await setupOrganizer(1_000_000);
      const hId4 = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep4, vault: v4 } = await createHackathon({
        organizer: org4,
        organizerAta: ata4,
        hackathonId: hId4,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });
      const { winnerAta: wa1 } = await setupWinner();
      const { winnerAta: wa2 } = await setupWinner();

      // 2 recipients but 3 share entries
      await expectError(
        () =>
          program.methods
            .releasePrize(hId4, [5_000, 3_000, 2_000])
            .accounts({
              organizer: org4.publicKey,
              usdcMint,
              hackathonEscrow: ep4,
              vault: v4,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: wa1, isSigner: false, isWritable: true },
              { pubkey: wa2, isSigner: false, isWritable: true },
            ])
            .signers([org4])
            .rpc(),
        "RecipientCountMismatch"
      );
    });

    it("rejects a recipient account not owned by the token program", async () => {
      const { organizer: org5, organizerAta: ata5 } = await setupOrganizer(1_000_000);
      const hId5 = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep5, vault: v5 } = await createHackathon({
        organizer: org5,
        organizerAta: ata5,
        hackathonId: hId5,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });

      // Pass a system account (owned by SystemProgram, not TokenProgram)
      const systemAccount = Keypair.generate().publicKey;

      await expectError(
        () =>
          program.methods
            .releasePrize(hId5, [10_000])
            .accounts({
              organizer: org5.publicKey,
              usdcMint,
              hackathonEscrow: ep5,
              vault: v5,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: systemAccount, isSigner: false, isWritable: true },
            ])
            .signers([org5])
            .rpc(),
        "InvalidRecipientAccount"
      );
    });

    it("rejects a recipient token account with the wrong mint", async () => {
      const { organizer: org6, organizerAta: ata6 } = await setupOrganizer(1_000_000);
      const hId6 = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep6, vault: v6 } = await createHackathon({
        organizer: org6,
        organizerAta: ata6,
        hackathonId: hId6,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });

      // Create a different mint and a token account for it
      const wrongMint = await createMint(
        provider.connection,
        payer,
        mintAuthority.publicKey,
        null,
        6
      );
      const wrongAta = await createAssociatedTokenAccount(
        provider.connection,
        payer,
        wrongMint,
        Keypair.generate().publicKey
      );

      await expectError(
        () =>
          program.methods
            .releasePrize(hId6, [10_000])
            .accounts({
              organizer: org6.publicKey,
              usdcMint,
              hackathonEscrow: ep6,
              vault: v6,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: wrongAta, isSigner: false, isWritable: true },
            ])
            .signers([org6])
            .rpc(),
        "InvalidRecipientMint"
      );
    });

    it("rejects an empty winner list", async () => {
      const { organizer: org, organizerAta: ata } = await setupOrganizer(1_000_000);
      const hId = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep, vault: v } = await createHackathon({
        organizer: org,
        organizerAta: ata,
        hackathonId: hId,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });

      await expectError(
        () =>
          program.methods
            .releasePrize(hId, [])
            .accounts({
              organizer: org.publicKey,
              usdcMint,
              hackathonEscrow: ep,
              vault: v,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([])
            .signers([org])
            .rpc(),
        "InvalidShares"
      );
    });

    it("rejects bps summing to less than 100%", async () => {
      const { organizer: org, organizerAta: ata } = await setupOrganizer(1_000_000);
      const hId = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep, vault: v } = await createHackathon({
        organizer: org,
        organizerAta: ata,
        hackathonId: hId,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });
      const { winnerAta } = await setupWinner();

      await expectError(
        () =>
          program.methods
            .releasePrize(hId, [5_000]) // only 50% — prize would be stranded
            .accounts({
              organizer: org.publicKey,
              usdcMint,
              hackathonEscrow: ep,
              vault: v,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: winnerAta, isSigner: false, isWritable: true },
            ])
            .signers([org])
            .rpc(),
        "InvalidShares"
      );
    });

    it("rejects bps overflow that wraps to a valid u16 value", async () => {
      // 7 × 10_000 = 70_000 wraps to 4_464 in u16, bypassing the old <= 10_000 check.
      // The u32 sum correctly sees 70_000 != 10_000 and rejects it.
      const { organizer: org, organizerAta: ata } = await setupOrganizer(1_000_000);
      const hId = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep, vault: v } = await createHackathon({
        organizer: org,
        organizerAta: ata,
        hackathonId: hId,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });
      const winners = await Promise.all(
        Array.from({ length: 7 }, () => setupWinner())
      );

      await expectError(
        () =>
          program.methods
            .releasePrize(hId, [10_000, 10_000, 10_000, 10_000, 10_000, 10_000, 10_000])
            .accounts({
              organizer: org.publicKey,
              usdcMint,
              hackathonEscrow: ep,
              vault: v,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts(
              winners.map((w) => ({ pubkey: w.winnerAta, isSigner: false, isWritable: true }))
            )
            .signers([org])
            .rpc(),
        "InvalidShares"
      );
    });

    it("single winner receives full prize and vault is drained to zero", async () => {
      const { organizer: org, organizerAta: ata } = await setupOrganizer(1_000_000);
      const hId = randomHackathonId();
      const now = Math.floor(Date.now() / 1000);
      const { escrowPda: ep, vault: v } = await createHackathon({
        organizer: org,
        organizerAta: ata,
        hackathonId: hId,
        prizeUsdc: 1_000_000,
        votingStart: new anchor.BN(now - 200),
        votingEnd: new anchor.BN(now - 100),
      });
      const { winnerAta } = await setupWinner();

      await program.methods
        .releasePrize(hId, [10_000])
        .accounts({
          organizer: org.publicKey,
          usdcMint,
          hackathonEscrow: ep,
          vault: v,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .remainingAccounts([{ pubkey: winnerAta, isSigner: false, isWritable: true }])
        .signers([org])
        .rpc();

      const winnerAcct = await getAccount(provider.connection, winnerAta);
      assert.equal(Number(winnerAcct.amount), 1_000_000);

      const vaultAcct = await getAccount(provider.connection, v);
      assert.equal(Number(vaultAcct.amount), 0, "vault must be fully drained");
    });

    it("rejects a double release on the same hackathon", async () => {
      // The first release_prize test already released this hackathon (status = Released)
      const { winnerAta } = await setupWinner();

      await expectError(
        () =>
          program.methods
            .releasePrize(hackathonId, [10_000])
            .accounts({
              organizer: organizer.publicKey,
              usdcMint,
              hackathonEscrow: escrowPda,
              vault,
              tokenProgram: TOKEN_PROGRAM_ID,
            })
            .remainingAccounts([
              { pubkey: winnerAta, isSigner: false, isWritable: true },
            ])
            .signers([organizer])
            .rpc(),
        "AlreadyReleased"
      );
    });
  });
});
