// Run `anchor build` before `anchor test` to generate target/idl/voting.json.
import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { Keypair, PublicKey, LAMPORTS_PER_SOL, SystemProgram } from "@solana/web3.js";
import { assert } from "chai";

describe("voting", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const program = anchor.workspace.Voting as Program<any>;

  // Shared across tests
  let teamLead: Keypair;
  let voter: Keypair;
  let hackathonId: PublicKey;
  let projectRecord: PublicKey;

  // ── Helpers ────────────────────────────────────────────────────────────────

  async function fund(pubkey: PublicKey, sol = 2): Promise<void> {
    const sig = await provider.connection.requestAirdrop(
      pubkey,
      sol * LAMPORTS_PER_SOL
    );
    const latest = await provider.connection.getLatestBlockhash();
    await provider.connection.confirmTransaction({ signature: sig, ...latest });
  }

  function findProjectPda(hackathonId: PublicKey, lead: PublicKey): PublicKey {
    const [pda] = PublicKey.findProgramAddressSync(
      [Buffer.from("project"), hackathonId.toBuffer(), lead.toBuffer()],
      program.programId
    );
    return pda;
  }

  function findVotePda(voter: PublicKey, project: PublicKey): PublicKey {
    const [pda] = PublicKey.findProgramAddressSync(
      [Buffer.from("vote"), voter.toBuffer(), project.toBuffer()],
      program.programId
    );
    return pda;
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
    teamLead = Keypair.generate();
    voter = Keypair.generate();
    hackathonId = Keypair.generate().publicKey;

    await Promise.all([fund(teamLead.publicKey), fund(voter.publicKey)]);

    projectRecord = findProjectPda(hackathonId, teamLead.publicKey);
  });

  // ── register_project ───────────────────────────────────────────────────────

  it("registers a project successfully", async () => {
    await program.methods
      .registerProject(hackathonId, "Seekerthon Demo")
      .accounts({
        teamLead: teamLead.publicKey,
        projectRecord,
        systemProgram: SystemProgram.programId,
      })
      .signers([teamLead])
      .rpc();

    const record = await program.account.projectRecord.fetch(projectRecord);
    assert.equal(record.name, "Seekerthon Demo");
    assert.equal(record.hackathonId.toBase58(), hackathonId.toBase58());
    assert.equal(record.teamLead.toBase58(), teamLead.publicKey.toBase58());
    assert.equal(record.totalVoteWeightBps.toNumber(), 0);
    assert.equal(record.uniqueVoters.toNumber(), 0);
  });

  it("rejects a project name longer than 64 bytes", async () => {
    const otherLead = Keypair.generate();
    await fund(otherLead.publicKey);
    const otherProject = findProjectPda(hackathonId, otherLead.publicKey);

    await expectError(
      () =>
        program.methods
          .registerProject(hackathonId, "x".repeat(65))
          .accounts({
            teamLead: otherLead.publicKey,
            projectRecord: otherProject,
            systemProgram: SystemProgram.programId,
          })
          .signers([otherLead])
          .rpc(),
      "NameTooLong"
    );
  });

  // ── cast_vote ──────────────────────────────────────────────────────────────

  it("casts a vote at base weight (1.0x = 10_000 bps)", async () => {
    const voteRecord = findVotePda(voter.publicKey, projectRecord);

    await program.methods
      .castVote(10_000)
      .accounts({
        voter: voter.publicKey,
        projectRecord,
        voteRecord,
        systemProgram: SystemProgram.programId,
      })
      .signers([voter])
      .rpc();

    const vote = await program.account.voteRecord.fetch(voteRecord);
    assert.equal(vote.weightBps, 10_000);
    assert.isTrue(vote.hasVoted);
    assert.equal(vote.voter.toBase58(), voter.publicKey.toBase58());
    assert.equal(vote.project.toBase58(), projectRecord.toBase58());

    const project = await program.account.projectRecord.fetch(projectRecord);
    assert.equal(project.totalVoteWeightBps.toNumber(), 10_000);
    assert.equal(project.uniqueVoters.toNumber(), 1);
  });

  it("casts a second vote from a different wallet at max weight (5.0x = 50_000 bps)", async () => {
    const voter2 = Keypair.generate();
    await fund(voter2.publicKey);
    const voteRecord2 = findVotePda(voter2.publicKey, projectRecord);

    await program.methods
      .castVote(50_000)
      .accounts({
        voter: voter2.publicKey,
        projectRecord,
        voteRecord: voteRecord2,
        systemProgram: SystemProgram.programId,
      })
      .signers([voter2])
      .rpc();

    const project = await program.account.projectRecord.fetch(projectRecord);
    assert.equal(project.totalVoteWeightBps.toNumber(), 60_000); // 10_000 + 50_000
    assert.equal(project.uniqueVoters.toNumber(), 2);
  });

  it("rejects weight below 1.0x (9_999 bps)", async () => {
    const v = Keypair.generate();
    await fund(v.publicKey);

    await expectError(
      () =>
        program.methods
          .castVote(9_999)
          .accounts({
            voter: v.publicKey,
            projectRecord,
            voteRecord: findVotePda(v.publicKey, projectRecord),
            systemProgram: SystemProgram.programId,
          })
          .signers([v])
          .rpc(),
      "InvalidWeight"
    );
  });

  it("rejects weight above 5.0x (50_001 bps)", async () => {
    const v = Keypair.generate();
    await fund(v.publicKey);

    await expectError(
      () =>
        program.methods
          .castVote(50_001)
          .accounts({
            voter: v.publicKey,
            projectRecord,
            voteRecord: findVotePda(v.publicKey, projectRecord),
            systemProgram: SystemProgram.programId,
          })
          .signers([v])
          .rpc(),
      "InvalidWeight"
    );
  });

  it("rejects a double vote from the same wallet", async () => {
    // voter already voted in the first cast_vote test.
    // `init` means the PDA cannot be re-initialized — Anchor returns 0x0 (account already in use).
    const voteRecord = findVotePda(voter.publicKey, projectRecord);

    await expectError(
      () =>
        program.methods
          .castVote(10_000)
          .accounts({
            voter: voter.publicKey,
            projectRecord,
            voteRecord,
            systemProgram: SystemProgram.programId,
          })
          .signers([voter])
          .rpc(),
      "0x0" // anchor error code for "account already in use"
    );
  });

  it("isolates vote counts — a second project is not affected by votes on the first", async () => {
    const lead2 = Keypair.generate();
    await fund(lead2.publicKey);
    const project2 = findProjectPda(hackathonId, lead2.publicKey);

    await program.methods
      .registerProject(hackathonId, "Second Project")
      .accounts({
        teamLead: lead2.publicKey,
        projectRecord: project2,
        systemProgram: SystemProgram.programId,
      })
      .signers([lead2])
      .rpc();

    // Vote on project2 from a fresh wallet
    const v = Keypair.generate();
    await fund(v.publicKey);

    await program.methods
      .castVote(20_000)
      .accounts({
        voter: v.publicKey,
        projectRecord: project2,
        voteRecord: findVotePda(v.publicKey, project2),
        systemProgram: SystemProgram.programId,
      })
      .signers([v])
      .rpc();

    // project2 should have 1 vote; original projectRecord unchanged at 2
    const p2 = await program.account.projectRecord.fetch(project2);
    assert.equal(p2.uniqueVoters.toNumber(), 1);
    assert.equal(p2.totalVoteWeightBps.toNumber(), 20_000);

    const p1 = await program.account.projectRecord.fetch(projectRecord);
    assert.equal(p1.uniqueVoters.toNumber(), 2); // unchanged
  });
});
