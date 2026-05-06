use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount};

declare_id!("DdNeeXHP6QUyNMq8ZGAQ7VsSAcEQ7FCCbXbX9DrFFS8t");

pub const MAX_MULTIPLIER_BPS: u16 = 50_000; // 5.0x in basis points
pub const BASE_WEIGHT_BPS: u16 = 10_000;    // 1.0x

#[program]
pub mod voting {
    use super::*;

    /// Register a new project for voting within a hackathon
    pub fn register_project(
        ctx: Context<RegisterProject>,
        hackathon_id: Pubkey,
        project_name: String,
    ) -> Result<()> {
        let project = &mut ctx.accounts.project_record;
        project.hackathon_id = hackathon_id;
        project.team_lead = ctx.accounts.team_lead.key();
        project.name = project_name;
        project.total_vote_weight_bps = 0;
        project.unique_voters = 0;
        project.bump = ctx.bumps.project_record;
        Ok(())
    }

    /// Cast a weighted vote for a project.
    /// One PDA per (voter, project) — structurally prevents double voting.
    pub fn cast_vote(
        ctx: Context<CastVote>,
        weight_bps: u16,
    ) -> Result<()> {
        require!(
            weight_bps >= BASE_WEIGHT_BPS && weight_bps <= MAX_MULTIPLIER_BPS,
            VotingError::InvalidWeight
        );

        let vote_record = &mut ctx.accounts.vote_record;
        require!(!vote_record.has_voted, VotingError::AlreadyVoted);

        let project_key = ctx.accounts.project_record.key();

        // Record the vote
        vote_record.voter = ctx.accounts.voter.key();
        vote_record.project = project_key;
        vote_record.weight_bps = weight_bps;
        vote_record.has_voted = true;
        vote_record.voted_at = Clock::get()?.unix_timestamp;
        vote_record.bump = ctx.bumps.vote_record;

        // Update project total
        let project = &mut ctx.accounts.project_record;
        project.total_vote_weight_bps = project
            .total_vote_weight_bps
            .checked_add(weight_bps as u64)
            .ok_or(VotingError::Overflow)?;
        project.unique_voters = project
            .unique_voters
            .checked_add(1)
            .ok_or(VotingError::Overflow)?;

        emit!(VoteCast {
            voter: ctx.accounts.voter.key(),
            project: project_key,
            hackathon_id: project.hackathon_id,
            weight_bps,
        });

        Ok(())
    }

    /// Lock SKR tokens in the staking vault to earn vote multiplier
    pub fn stake_skr(ctx: Context<StakeSkr>, amount: u64) -> Result<()> {
        let staking_account = &mut ctx.accounts.staking_account;
        staking_account.owner = ctx.accounts.voter.key();
        staking_account.amount = staking_account.amount.checked_add(amount).ok_or(VotingError::Overflow)?;
        staking_account.bump = ctx.bumps.staking_account;

        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                token::Transfer {
                    from: ctx.accounts.voter_skr_ata.to_account_info(),
                    to: ctx.accounts.vault_skr_ata.to_account_info(),
                    authority: ctx.accounts.voter.to_account_info(),
                },
            ),
            amount,
        )?;

        emit!(Staked {
            voter: ctx.accounts.voter.key(),
            amount,
            new_total: staking_account.amount,
        });

        Ok(())
    }

    /// Unstake SKR — returns tokens to voter
    pub fn unstake_skr(ctx: Context<UnstakeSkr>, amount: u64) -> Result<()> {
        let staking_account = &mut ctx.accounts.staking_account;
        require!(staking_account.amount >= amount, VotingError::InsufficientStake);
        staking_account.amount -= amount;

        let seeds = &[
            b"stake",
            ctx.accounts.voter.key.as_ref(),
            ctx.accounts.skr_mint.key.as_ref(),
            &[staking_account.bump],
        ];
        let signer = &[&seeds[..]];

        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                token::Transfer {
                    from: ctx.accounts.vault_skr_ata.to_account_info(),
                    to: ctx.accounts.voter_skr_ata.to_account_info(),
                    authority: staking_account.to_account_info(),
                },
                signer,
            ),
            amount,
        )?;

        Ok(())
    }
}

// ── Accounts ──────────────────────────────────────────────────────────────

#[derive(Accounts)]
#[instruction(hackathon_id: Pubkey, project_name: String)]
pub struct RegisterProject<'info> {
    #[account(mut)]
    pub team_lead: Signer<'info>,

    #[account(
        init,
        payer = team_lead,
        space = ProjectRecord::LEN,
        seeds = [b"project", hackathon_id.as_ref(), team_lead.key().as_ref()],
        bump,
    )]
    pub project_record: Account<'info, ProjectRecord>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct CastVote<'info> {
    #[account(mut)]
    pub voter: Signer<'info>,

    #[account(mut)]
    pub project_record: Account<'info, ProjectRecord>,

    #[account(
        init_if_needed,
        payer = voter,
        space = VoteRecord::LEN,
        seeds = [b"vote", voter.key().as_ref(), project_record.key().as_ref()],
        bump,
    )]
    pub vote_record: Account<'info, VoteRecord>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct StakeSkr<'info> {
    #[account(mut)]
    pub voter: Signer<'info>,

    /// CHECK: read-only mint account — only its key is used for PDA derivation
    pub skr_mint: AccountInfo<'info>,

    #[account(mut)]
    pub voter_skr_ata: Account<'info, TokenAccount>,

    #[account(mut)]
    pub vault_skr_ata: Account<'info, TokenAccount>,

    #[account(
        init_if_needed,
        payer = voter,
        space = StakingAccount::LEN,
        seeds = [b"stake", voter.key().as_ref(), skr_mint.key().as_ref()],
        bump,
    )]
    pub staking_account: Account<'info, StakingAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UnstakeSkr<'info> {
    #[account(mut)]
    pub voter: Signer<'info>,
    /// CHECK: read-only mint account — only its key is used for PDA derivation
    pub skr_mint: AccountInfo<'info>,
    #[account(mut)]
    pub voter_skr_ata: Account<'info, TokenAccount>,
    #[account(mut)]
    pub vault_skr_ata: Account<'info, TokenAccount>,
    #[account(mut, seeds = [b"stake", voter.key().as_ref(), skr_mint.key().as_ref()], bump = staking_account.bump)]
    pub staking_account: Account<'info, StakingAccount>,
    pub token_program: Program<'info, Token>,
}

// ── State ──────────────────────────────────────────────────────────────────

#[account]
pub struct ProjectRecord {
    pub hackathon_id: Pubkey,       // 32
    pub team_lead: Pubkey,          // 32
    pub name: String,               // 4 + 64
    pub total_vote_weight_bps: u64, // 8
    pub unique_voters: u64,         // 8
    pub bump: u8,                   // 1
}

impl ProjectRecord {
    pub const LEN: usize = 8 + 32 + 32 + (4 + 64) + 8 + 8 + 1;
}

#[account]
pub struct VoteRecord {
    pub voter: Pubkey,      // 32
    pub project: Pubkey,    // 32
    pub weight_bps: u16,    // 2
    pub has_voted: bool,    // 1
    pub voted_at: i64,      // 8
    pub bump: u8,           // 1
}

impl VoteRecord {
    pub const LEN: usize = 8 + 32 + 32 + 2 + 1 + 8 + 1;
}

#[account]
pub struct StakingAccount {
    pub owner: Pubkey,  // 32
    pub amount: u64,    // 8
    pub bump: u8,       // 1
}

impl StakingAccount {
    pub const LEN: usize = 8 + 32 + 8 + 1;
}

// ── Events ──────────────────────────────────────────────────────────────────

#[event]
pub struct VoteCast {
    pub voter: Pubkey,
    pub project: Pubkey,
    pub hackathon_id: Pubkey,
    pub weight_bps: u16,
}

#[event]
pub struct Staked {
    pub voter: Pubkey,
    pub amount: u64,
    pub new_total: u64,
}

// ── Errors ──────────────────────────────────────────────────────────────────

#[error_code]
pub enum VotingError {
    #[msg("Already voted for this project")]
    AlreadyVoted,
    #[msg("Weight must be between 1.0x and 5.0x")]
    InvalidWeight,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Insufficient staked amount")]
    InsufficientStake,
}
