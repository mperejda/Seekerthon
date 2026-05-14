import * as anchor from "@coral-xyz/anchor";
import {
  Ed25519Program,
  Keypair,
  LAMPORTS_PER_SOL,
  PublicKey,
  SYSVAR_INSTRUCTIONS_PUBKEY,
  SYSVAR_RENT_PUBKEY,
  SystemProgram,
} from "@solana/web3.js";
import {
  ASSOCIATED_TOKEN_PROGRAM_ID,
  TOKEN_PROGRAM_ID,
  createAssociatedTokenAccount,
  createMint,
  getAccount,
  getAssociatedTokenAddress,
  mintTo,
} from "@solana/spl-token";
import { assert } from "chai";

const CLAIM_PREFIX = Buffer.from("seekerthon-claim:v1");

describe("escrow winner claim", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace.Escrow as any;
  const payer = (provider.wallet as anchor.Wallet).payer;

  let usdcMint: PublicKey;
  let mintAuthority: Keypair;
  let platformAdmin: Keypair;

  async function fund(pubkey: PublicKey, sol = 2): Promise<void> {
    const sig = await provider.connection.requestAirdrop(pubkey, sol * LAMPORTS_PER_SOL);
    const latest = await provider.connection.getLatestBlockhash();
    await provider.connection.confirmTransaction({ signature: sig, ...latest });
  }

  function randomId(): number[] {
    return Array.from(Keypair.generate().publicKey.toBuffer().subarray(0, 16));
  }

  function findEscrowPda(hackathonId: number[]): PublicKey {
    return PublicKey.findProgramAddressSync(
      [Buffer.from("hackathon_escrow"), Buffer.from(hackathonId)],
      program.programId,
    )[0];
  }

  function findProjectPda(escrow: PublicKey, projectId: number[]): PublicKey {
    return PublicKey.findProgramAddressSync(
      [Buffer.from("project"), escrow.toBuffer(), Buffer.from(projectId)],
      program.programId,
    )[0];
  }

  function claimMessage(args: {
    escrow: PublicKey;
    hackathonId: number[];
    projectId: number[];
    winner: PublicKey;
    prizeUsdc: number;
    expiresAt: anchor.BN;
    nonce: number[];
  }): Buffer {
    const prize = Buffer.alloc(8);
    prize.writeBigUInt64LE(BigInt(args.prizeUsdc));
    const expires = Buffer.alloc(8);
    expires.writeBigInt64LE(BigInt(args.expiresAt.toString()));
    return Buffer.concat([
      CLAIM_PREFIX,
      program.programId.toBuffer(),
      args.escrow.toBuffer(),
      Buffer.from(args.hackathonId),
      Buffer.from(args.projectId),
      args.winner.toBuffer(),
      prize,
      expires,
      Buffer.from(args.nonce),
    ]);
  }

  async function setupOrganizer(usdcAmount: number) {
    const organizer = Keypair.generate();
    await fund(organizer.publicKey, 3);
    const organizerAta = await createAssociatedTokenAccount(
      provider.connection,
      payer,
      usdcMint,
      organizer.publicKey,
    );
    await mintTo(provider.connection, payer, usdcMint, organizerAta, mintAuthority, usdcAmount);
    return { organizer, organizerAta };
  }

  async function createEscrow(opts: {
    organizer: Keypair;
    organizerAta: PublicKey;
    hackathonId: number[];
    prizeUsdc: number;
    votingStart: anchor.BN;
    votingEnd: anchor.BN;
  }) {
    const escrow = findEscrowPda(opts.hackathonId);
    const vault = await getAssociatedTokenAddress(usdcMint, escrow, true);
    await program.methods
      .createHackathon(opts.hackathonId, new anchor.BN(opts.prizeUsdc), opts.votingStart, opts.votingEnd)
      .accounts({
        organizer: opts.organizer.publicKey,
        platformAdmin: platformAdmin.publicKey,
        usdcMint,
        hackathonEscrow: escrow,
        vault,
        organizerUsdcAta: opts.organizerAta,
        tokenProgram: TOKEN_PROGRAM_ID,
        associatedTokenProgram: ASSOCIATED_TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .signers([opts.organizer, platformAdmin])
      .rpc();
    return { escrow, vault };
  }

  async function createEscrowWithRegistrationWindow(opts: {
    prizeUsdc?: number;
    registrationSeconds?: number;
    votingSeconds?: number;
  } = {}) {
    const prizeUsdc = opts.prizeUsdc ?? 1_000_000;
    const registrationSeconds = opts.registrationSeconds ?? 5;
    const votingSeconds = opts.votingSeconds ?? 1;
    const { organizer, organizerAta } = await setupOrganizer(prizeUsdc);
    const hackathonId = randomId();
    const now = await currentUnix();
    const votingStart = now + registrationSeconds;
    const votingEnd = votingStart + votingSeconds;
    const { escrow, vault } = await createEscrow({
      organizer,
      organizerAta,
      hackathonId,
      prizeUsdc,
      votingStart: new anchor.BN(votingStart),
      votingEnd: new anchor.BN(votingEnd),
    });
    return { organizer, organizerAta, hackathonId, prizeUsdc, votingStart, votingEnd, escrow, vault };
  }

  async function registerProject(opts: {
    teamLead: Keypair;
    escrow: PublicKey;
    projectId: number[];
  }) {
    const projectRecord = findProjectPda(opts.escrow, opts.projectId);
    await program.methods
      .registerProject(opts.projectId)
      .accounts({
        teamLead: opts.teamLead.publicKey,
        hackathonEscrow: opts.escrow,
        projectRecord,
        systemProgram: SystemProgram.programId,
      })
      .signers([opts.teamLead])
      .rpc();
    return projectRecord;
  }

  async function markSubmitted(opts: {
    escrow: PublicKey;
    projectRecord: PublicKey;
    hackathonId: number[];
    projectId: number[];
  }) {
    await program.methods
      .markSubmitted(opts.hackathonId, opts.projectId)
      .accounts({
        platformAdmin: platformAdmin.publicKey,
        hackathonEscrow: opts.escrow,
        projectRecord: opts.projectRecord,
      })
      .signers([platformAdmin])
      .rpc();
  }

  async function expectError(fn: () => Promise<unknown>, fragment: string): Promise<void> {
    try {
      await fn();
      assert.fail(`Expected error containing "${fragment}" but transaction succeeded`);
    } catch (err: unknown) {
      const msg = String(err);
      if (msg.includes("Expected error containing")) throw err;
      assert.include(msg, fragment, `Wrong error: ${msg}`);
    }
  }

  function clearBlockhashCache(): void {
    (provider.connection as any)._blockhashInfo = {
      latestBlockhash: null,
      lastFetch: 0,
      transactionSignatures: [],
      simulatedSignatures: [],
    };
  }

  async function currentUnix(): Promise<number> {
    const slot = await provider.connection.getSlot();
    return (await provider.connection.getBlockTime(slot)) ?? Math.floor(Date.now() / 1000);
  }

  async function tick(): Promise<void> {
    const sig = await provider.connection.requestAirdrop(payer.publicKey, 1);
    const latest = await provider.connection.getLatestBlockhash();
    await provider.connection.confirmTransaction({ signature: sig, ...latest });
  }

  async function waitUntilUnix(targetUnix: number): Promise<void> {
    const current = await currentUnix();
    if (current >= targetUnix) return;

    try {
      const currentSlot = await provider.connection.getSlot();
      const secondsToAdvance = targetUnix - current;
      const targetSlot = currentSlot + Math.max(secondsToAdvance * 8, 64);
      await (provider.connection as any)._rpcRequest("warpSlot", [targetSlot]);
      clearBlockhashCache();
      await tick();
      clearBlockhashCache();
      if (await currentUnix() >= targetUnix) return;
    } catch {
      // warpSlot is only available on local test validators. Fall back to ticking.
    }

    for (let i = 0; i < 60; i++) {
      await tick();
      if (await currentUnix() >= targetUnix) return;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new Error(`validator clock did not reach ${targetUnix}`);
  }

  function claimSigIx(args: {
    signer: Keypair;
    escrow: PublicKey;
    hackathonId: number[];
    projectId: number[];
    winner: PublicKey;
    prizeUsdc: number;
    expiresAt: anchor.BN;
    nonce: number[];
  }) {
    return Ed25519Program.createInstructionWithPrivateKey({
      privateKey: args.signer.secretKey,
      message: claimMessage(args),
    });
  }

  before(async () => {
    (provider.connection as any)._disableBlockhashCaching = true;
    mintAuthority = Keypair.generate();
    platformAdmin = Keypair.generate();
    await fund(mintAuthority.publicKey);
    await fund(platformAdmin.publicKey);
    usdcMint = await createMint(provider.connection, payer, mintAuthority.publicKey, null, 6);
  });

  // ── Happy path ────────────────────────────────────────────────────────────────

  it("registers a project and lets the certified winner claim", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const now = await currentUnix();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });

    const escrowState = await program.account.hackathonEscrow.fetch(escrow);
    assert.equal(escrowState.projectCount, 1);
    assert.equal(escrowState.submittedProjectCount, 1);

    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN(now + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });

    await program.methods
      .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
      .preInstructions([sigIx])
      .accounts({
        winner: winner.publicKey,
        usdcMint,
        hackathonEscrow: escrow,
        projectRecord,
        vault,
        winnerUsdcAta: winnerAta,
        instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([winner])
      .rpc();

    const winnerAccount = await getAccount(provider.connection, winnerAta);
    assert.equal(Number(winnerAccount.amount), prizeUsdc);
  });

  it("allows refund when projects are registered but not submitted", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { organizer, organizerAta, hackathonId, votingEnd, escrow, vault } = setup;
    const teamLead = Keypair.generate();
    await fund(teamLead.publicKey);
    const projectId = randomId();
    await registerProject({ teamLead, escrow, projectId });
    // Deliberately skip markSubmitted — registered-only must not block the refund.

    await waitUntilUnix(votingEnd);

    await program.methods
      .refundEscrow(hackathonId)
      .accounts({
        organizer: organizer.publicKey,
        usdcMint,
        hackathonEscrow: escrow,
        vault,
        organizerUsdcAta: organizerAta,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([organizer])
      .rpc();

    const organizerAccount = await getAccount(provider.connection, organizerAta);
    assert.equal(Number(organizerAccount.amount), setup.prizeUsdc);
  });

  it("refunds the organizer when no projects registered", async () => {
    const prizeUsdc = 1_000_000;
    const { organizer, organizerAta } = await setupOrganizer(prizeUsdc);
    const hackathonId = randomId();
    const now = await currentUnix();
    const votingEnd = now + 2;
    const { escrow, vault } = await createEscrow({
      organizer,
      organizerAta,
      hackathonId,
      prizeUsdc,
      votingStart: new anchor.BN(now + 1),
      votingEnd: new anchor.BN(votingEnd),
    });

    await waitUntilUnix(votingEnd);

    await program.methods
      .refundEscrow(hackathonId)
      .accounts({
        organizer: organizer.publicKey,
        usdcMint,
        hackathonEscrow: escrow,
        vault,
        organizerUsdcAta: organizerAta,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([organizer])
      .rpc();

    const organizerAccount = await getAccount(provider.connection, organizerAta);
    assert.equal(Number(organizerAccount.amount), prizeUsdc);
  });

  it("rejects project registration after submissions close", async () => {
    const prizeUsdc = 1_000_000;
    const { organizer, organizerAta } = await setupOrganizer(prizeUsdc);
    const teamLead = Keypair.generate();
    await fund(teamLead.publicKey);
    const hackathonId = randomId();
    const projectId = randomId();
    const now = await currentUnix();
    const votingStart = now + 1;
    const { escrow } = await createEscrow({
      organizer,
      organizerAta,
      hackathonId,
      prizeUsdc,
      votingStart: new anchor.BN(votingStart),
      votingEnd: new anchor.BN(now + 3),
    });
    const projectRecord = findProjectPda(escrow, projectId);

    await waitUntilUnix(votingStart);

    await expectError(
      () =>
        program.methods
          .registerProject(projectId)
          .accounts({
            teamLead: teamLead.publicKey,
            hackathonEscrow: escrow,
            projectRecord,
            systemProgram: SystemProgram.programId,
          })
          .signers([teamLead])
          .rpc(),
      "RegistrationClosed",
    );
  });

  it("rejects forged winner certificates", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    const attackerAdmin = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const now = await currentUnix();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN(now + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: attackerAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "InvalidWinnerCertificate",
    );
  });

  it("rejects claims by a wallet that does not own the project record", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    const attacker = Keypair.generate();
    await fund(winner.publicKey);
    await fund(attacker.publicKey);
    const attackerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, attacker.publicKey);
    const projectId = randomId();
    const now = await currentUnix();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN(now + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: attacker.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: attacker.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: attackerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([attacker])
          .rpc(),
      "InvalidProjectRecord",
    );
  });

  it("rejects expired winner certificates", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const now = await currentUnix();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN(now - 1);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "CertificateExpired",
    );
  });

  it("rejects claims before voting has ended", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "VotingNotEnded",
    );
  });

  it("rejects refunds before voting has ended", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { organizer, organizerAta, hackathonId, escrow, vault } = setup;

    await expectError(
      () =>
        program.methods
          .refundEscrow(hackathonId)
          .accounts({
            organizer: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            vault,
            organizerUsdcAta: organizerAta,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([organizer])
          .rpc(),
      "VotingNotEnded",
    );
  });

  it("rejects claims for the wrong prize amount", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await waitUntilUnix(votingEnd);

    const wrongPrizeUsdc = prizeUsdc - 1;
    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc: wrongPrizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(wrongPrizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "InvalidPrize",
    );
  });

  it("rejects double claims after the prize is released", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const firstNonce = randomId();
    const firstSigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce: firstNonce });
    await program.methods
      .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, firstNonce)
      .preInstructions([firstSigIx])
      .accounts({
        winner: winner.publicKey,
        usdcMint,
        hackathonEscrow: escrow,
        projectRecord,
        vault,
        winnerUsdcAta: winnerAta,
        instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([winner])
      .rpc();

    const secondNonce = randomId();
    const secondSigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce: secondNonce });
    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, secondNonce)
          .preInstructions([secondSigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "AlreadyReleased",
    );
  });

  it("rejects organizer claims even with a valid certificate", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { organizer, organizerAta, hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead: organizer, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: organizer.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: organizerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([organizer])
          .rpc(),
      "OrganizerCannotClaim",
    );
  });

  it("rejects replaying a valid certificate against another project", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const certifiedProjectId = randomId();
    const replayProjectId = randomId();
    const certifiedRecord = await registerProject({ teamLead: winner, escrow, projectId: certifiedProjectId });
    const replayProjectRecord = await registerProject({ teamLead: winner, escrow, projectId: replayProjectId });
    await markSubmitted({ escrow, projectRecord: certifiedRecord, hackathonId, projectId: certifiedProjectId });
    await markSubmitted({ escrow, projectRecord: replayProjectRecord, hackathonId, projectId: replayProjectId });
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({
      signer: platformAdmin,
      escrow,
      hackathonId,
      projectId: certifiedProjectId,
      winner: winner.publicKey,
      prizeUsdc,
      expiresAt,
      nonce,
    });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, replayProjectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord: replayProjectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "InvalidWinnerCertificate",
    );
  });

  it("rejects claims with the wrong mint", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    const wrongMint = await createMint(provider.connection, payer, mintAuthority.publicKey, null, 6);
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint: wrongMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "InvalidMint",
    );
  });

  // ── Security tests (OtterSec) ─────────────────────────────────────────────────

  it("[security] rejects claim_prize without mark_submitted", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    // Deliberately skip markSubmitted.
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "ProjectNotSubmitted",
    );
  });

  it("[security] rejects mark_submitted from non-admin", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, escrow } = setup;
    const teamLead = Keypair.generate();
    await fund(teamLead.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead, escrow, projectId });
    const fakeAdmin = Keypair.generate();
    await fund(fakeAdmin.publicKey);

    await expectError(
      () =>
        program.methods
          .markSubmitted(hackathonId, projectId)
          .accounts({
            platformAdmin: fakeAdmin.publicKey,
            hackathonEscrow: escrow,
            projectRecord,
          })
          .signers([fakeAdmin])
          .rpc(),
      "NotAuthorized",
    );
  });

  it("[security] mark_submitted is idempotent and does not double-count", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, escrow } = setup;
    const teamLead = Keypair.generate();
    await fund(teamLead.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead, escrow, projectId });

    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId }); // second call

    const state = await program.account.hackathonEscrow.fetch(escrow);
    assert.equal(state.submittedProjectCount, 1, "double mark_submitted must not increment counter twice");
    const record = await program.account.projectRecord.fetch(projectRecord);
    assert.isTrue(record.isSubmitted);
  });

  it("[security] rejects refund when submitted projects exist", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { organizer, organizerAta, hackathonId, votingEnd, escrow, vault } = setup;
    const teamLead = Keypair.generate();
    await fund(teamLead.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });

    await waitUntilUnix(votingEnd);

    await expectError(
      () =>
        program.methods
          .refundEscrow(hackathonId)
          .accounts({
            organizer: organizer.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            vault,
            organizerUsdcAta: organizerAta,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([organizer])
          .rpc(),
      "SubmittedProjectsExist",
    );
  });

  it("[security] rejects mark_submitted on a released escrow", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const winnerProjectId = randomId();
    const winnerRecord = await registerProject({ teamLead: winner, escrow, projectId: winnerProjectId });
    await markSubmitted({ escrow, projectRecord: winnerRecord, hackathonId, projectId: winnerProjectId });

    // Register a second project but do not submit it yet.
    const other = Keypair.generate();
    await fund(other.publicKey);
    const otherProjectId = randomId();
    const otherRecord = await registerProject({ teamLead: other, escrow, projectId: otherProjectId });

    await waitUntilUnix(votingEnd);

    // Winner claims, releasing the escrow.
    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId: winnerProjectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });
    await program.methods
      .claimPrize(hackathonId, winnerProjectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
      .preInstructions([sigIx])
      .accounts({
        winner: winner.publicKey,
        usdcMint,
        hackathonEscrow: escrow,
        projectRecord: winnerRecord,
        vault,
        winnerUsdcAta: winnerAta,
        instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([winner])
      .rpc();

    // Attempting mark_submitted on the now-released escrow must fail.
    await expectError(
      () => markSubmitted({ escrow, projectRecord: otherRecord, hackathonId, projectId: otherProjectId }),
      "AlreadyReleased",
    );
  });

  it("[security] rejects claim with Ed25519 instruction placed after claim_prize", async () => {
    const setup = await createEscrowWithRegistrationWindow();
    const { hackathonId, prizeUsdc, votingEnd, escrow, vault } = setup;
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);
    const projectId = randomId();
    const projectRecord = await registerProject({ teamLead: winner, escrow, projectId });
    await markSubmitted({ escrow, projectRecord, hackathonId, projectId });
    await waitUntilUnix(votingEnd);

    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    // Valid signature — but placed AFTER claim_prize, so the contract cannot see it.
    const sigIx = claimSigIx({ signer: platformAdmin, escrow, hackathonId, projectId, winner: winner.publicKey, prizeUsdc, expiresAt, nonce });

    await expectError(
      () =>
        program.methods
          .claimPrize(hackathonId, projectId, new anchor.BN(prizeUsdc), expiresAt, nonce)
          .postInstructions([sigIx])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: escrow,
            projectRecord,
            vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "InvalidWinnerCertificate",
    );
  });

  it("[security] rejects cross-escrow certificate replay", async () => {
    // Winner holds a valid cert for escrowA but tries to claim against escrowB.
    const setupA = await createEscrowWithRegistrationWindow();
    const setupB = await createEscrowWithRegistrationWindow();
    const winner = Keypair.generate();
    await fund(winner.publicKey);
    const winnerAta = await createAssociatedTokenAccount(provider.connection, payer, usdcMint, winner.publicKey);

    const projectIdA = randomId();
    const projectIdB = randomId();
    const recordA = await registerProject({ teamLead: winner, escrow: setupA.escrow, projectId: projectIdA });
    const recordB = await registerProject({ teamLead: winner, escrow: setupB.escrow, projectId: projectIdB });
    await markSubmitted({ escrow: setupA.escrow, projectRecord: recordA, hackathonId: setupA.hackathonId, projectId: projectIdA });
    await markSubmitted({ escrow: setupB.escrow, projectRecord: recordB, hackathonId: setupB.hackathonId, projectId: projectIdB });

    const laterVotingEnd = Math.max(setupA.votingEnd, setupB.votingEnd);
    await waitUntilUnix(laterVotingEnd);

    const expiresAt = new anchor.BN((await currentUnix()) + 10_000);
    const nonce = randomId();
    // Certificate is for escrowA / hackathonA / projectA.
    const sigIxA = claimSigIx({
      signer: platformAdmin,
      escrow: setupA.escrow,
      hackathonId: setupA.hackathonId,
      projectId: projectIdA,
      winner: winner.publicKey,
      prizeUsdc: setupA.prizeUsdc,
      expiresAt,
      nonce,
    });

    // Attempt to use escrowA's certificate to claim escrowB's prize.
    await expectError(
      () =>
        program.methods
          .claimPrize(setupB.hackathonId, projectIdB, new anchor.BN(setupB.prizeUsdc), expiresAt, nonce)
          .preInstructions([sigIxA])
          .accounts({
            winner: winner.publicKey,
            usdcMint,
            hackathonEscrow: setupB.escrow,
            projectRecord: recordB,
            vault: setupB.vault,
            winnerUsdcAta: winnerAta,
            instructions: SYSVAR_INSTRUCTIONS_PUBKEY,
            tokenProgram: TOKEN_PROGRAM_ID,
          })
          .signers([winner])
          .rpc(),
      "InvalidWinnerCertificate",
    );
  });
});
