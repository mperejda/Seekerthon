use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token::{self, Mint, Token, TokenAccount, Transfer},
};

declare_id!("GCiJViWButEvTMgRb1HMfJLDYU3ceKyNHvjWQXMUEGxs");

/// USDC has 6 decimal places — all prize amounts are stored in base units (micro-USDC).
pub const USDC_DECIMALS: u8 = 6;

#[program]
pub mod escrow {
    use super::*;

    /// Organizer creates a hackathon and deposits the USDC prize pool into an escrow vault.
    pub fn create_hackathon(
        ctx: Context<CreateHackathon>,
        hackathon_id: [u8; 16],
        prize_usdc: u64,   // base units (1 USDC = 1_000_000)
        voting_start: i64,
        voting_end: i64,
    ) -> Result<()> {
        require!(prize_usdc > 0, EscrowError::InvalidPrize);

        let escrow = &mut ctx.accounts.hackathon_escrow;
        escrow.organizer = ctx.accounts.organizer.key();
        escrow.hackathon_id = hackathon_id;
        escrow.prize_usdc = prize_usdc;
        escrow.usdc_mint = ctx.accounts.usdc_mint.key();
        escrow.voting_start = voting_start;
        escrow.voting_end = voting_end;
        escrow.status = HackathonEscrowStatus::Active;
        escrow.bump = ctx.bumps.hackathon_escrow;

        // Transfer USDC from organizer's ATA into the escrow vault
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.organizer_usdc_ata.to_account_info(),
                    to: ctx.accounts.vault.to_account_info(),
                    authority: ctx.accounts.organizer.to_account_info(),
                },
            ),
            prize_usdc,
        )?;

        emit!(HackathonCreated {
            hackathon_id,
            organizer: ctx.accounts.organizer.key(),
            prize_usdc,
        });

        Ok(())
    }

    /// Organizer verifies the winning project's tech and releases USDC prize to winners.
    /// Winner wallets and their split are passed via remaining_accounts + winner_share_bps.
    /// Shares must sum to ≤ 10_000 bps (100%). Any remainder stays in the vault.
    pub fn release_prize<'info>(
        ctx: Context<'_, '_, '_, 'info, ReleasePrize<'info>>,
        hackathon_id: [u8; 16],
        winner_share_bps: Vec<u16>,
    ) -> Result<()> {
        require!(
            ctx.accounts.hackathon_escrow.organizer == ctx.accounts.organizer.key(),
            EscrowError::NotOrganizer,
        );
        require!(
            ctx.accounts.hackathon_escrow.status == HackathonEscrowStatus::Active,
            EscrowError::AlreadyReleased,
        );

        let total_bps: u16 = winner_share_bps.iter().sum();
        require!(total_bps <= 10_000, EscrowError::InvalidShares);

        let prize = ctx.accounts.hackathon_escrow.prize_usdc;
        let bump = ctx.accounts.hackathon_escrow.bump;
        let seeds: &[&[u8]] = &[b"hackathon_escrow", hackathon_id.as_ref(), &[bump]];
        let signer_seeds = &[seeds];

        let vault_info = ctx.accounts.vault.to_account_info();
        let authority_info = ctx.accounts.hackathon_escrow.to_account_info();
        let token_program_info = ctx.accounts.token_program.to_account_info();

        // Transfer each winner's share from vault to their USDC ATA
        for (i, recipient_ata) in ctx.remaining_accounts.iter().enumerate() {
            let share_bps = winner_share_bps.get(i).copied().unwrap_or(0) as u64;
            let amount = prize.checked_mul(share_bps).unwrap() / 10_000;
            if amount == 0 {
                continue;
            }
            token::transfer(
                CpiContext::new_with_signer(
                    token_program_info.clone(),
                    Transfer {
                        from: vault_info.clone(),
                        to: recipient_ata.to_account_info(),
                        authority: authority_info.clone(),
                    },
                    signer_seeds,
                ),
                amount,
            )?;
        }

        ctx.accounts.hackathon_escrow.status = HackathonEscrowStatus::Released;

        emit!(PrizeReleased {
            hackathon_id,
            prize_usdc: prize,
        });

        Ok(())
    }

    /// Emergency refund — returns USDC to organizer if hackathon is cancelled before voting.
    pub fn refund<'info>(
        ctx: Context<'_, '_, '_, 'info, Refund<'info>>,
        hackathon_id: [u8; 16],
    ) -> Result<()> {
        require!(
            ctx.accounts.hackathon_escrow.organizer == ctx.accounts.organizer.key(),
            EscrowError::NotOrganizer,
        );
        require!(
            Clock::get()?.unix_timestamp < ctx.accounts.hackathon_escrow.voting_start,
            EscrowError::VotingAlreadyStarted,
        );

        let amount = ctx.accounts.hackathon_escrow.prize_usdc;
        let bump = ctx.accounts.hackathon_escrow.bump;
        let seeds: &[&[u8]] = &[b"hackathon_escrow", hackathon_id.as_ref(), &[bump]];
        let signer_seeds = &[seeds];

        let vault_info = ctx.accounts.vault.to_account_info();
        let dest_info = ctx.accounts.organizer_usdc_ata.to_account_info();
        let authority_info = ctx.accounts.hackathon_escrow.to_account_info();
        let token_program_info = ctx.accounts.token_program.to_account_info();

        token::transfer(
            CpiContext::new_with_signer(
                token_program_info,
                Transfer {
                    from: vault_info,
                    to: dest_info,
                    authority: authority_info,
                },
                signer_seeds,
            ),
            amount,
        )?;

        ctx.accounts.hackathon_escrow.status = HackathonEscrowStatus::Refunded;
        Ok(())
    }
}

// ── Accounts ──────────────────────────────────────────────────────────────────

#[derive(Accounts)]
#[instruction(hackathon_id: [u8; 16])]
pub struct CreateHackathon<'info> {
    #[account(mut)]
    pub organizer: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = organizer,
        space = HackathonEscrow::LEN,
        seeds = [b"hackathon_escrow", hackathon_id.as_ref()],
        bump,
    )]
    pub hackathon_escrow: Account<'info, HackathonEscrow>,

    /// Vault: ATA owned by the escrow PDA, holds the USDC prize pool.
    #[account(
        init,
        payer = organizer,
        associated_token::mint = usdc_mint,
        associated_token::authority = hackathon_escrow,
    )]
    pub vault: Account<'info, TokenAccount>,

    /// Organizer's USDC ATA — USDC is debited from here.
    #[account(
        mut,
        associated_token::mint = usdc_mint,
        associated_token::authority = organizer,
    )]
    pub organizer_usdc_ata: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
#[instruction(hackathon_id: [u8; 16])]
pub struct ReleasePrize<'info> {
    #[account(mut)]
    pub organizer: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        mut,
        seeds = [b"hackathon_escrow", hackathon_id.as_ref()],
        bump = hackathon_escrow.bump,
    )]
    pub hackathon_escrow: Account<'info, HackathonEscrow>,

    #[account(
        mut,
        associated_token::mint = usdc_mint,
        associated_token::authority = hackathon_escrow,
    )]
    pub vault: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    // Winner USDC ATAs passed in remaining_accounts
}

#[derive(Accounts)]
#[instruction(hackathon_id: [u8; 16])]
pub struct Refund<'info> {
    #[account(mut)]
    pub organizer: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        mut,
        seeds = [b"hackathon_escrow", hackathon_id.as_ref()],
        bump = hackathon_escrow.bump,
    )]
    pub hackathon_escrow: Account<'info, HackathonEscrow>,

    #[account(
        mut,
        associated_token::mint = usdc_mint,
        associated_token::authority = hackathon_escrow,
    )]
    pub vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        associated_token::mint = usdc_mint,
        associated_token::authority = organizer,
    )]
    pub organizer_usdc_ata: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

// ── State ──────────────────────────────────────────────────────────────────────

#[derive(AnchorSerialize, AnchorDeserialize, Clone, PartialEq)]
pub enum HackathonEscrowStatus {
    Active,
    Released,
    Refunded,
}

#[account]
pub struct HackathonEscrow {
    pub organizer: Pubkey,              // 32
    pub usdc_mint: Pubkey,              // 32
    pub hackathon_id: [u8; 16],         // 16
    pub prize_usdc: u64,                // 8  (base units, 6 decimals)
    pub voting_start: i64,              // 8
    pub voting_end: i64,                // 8
    pub status: HackathonEscrowStatus,  // 1
    pub bump: u8,                       // 1
}

impl HackathonEscrow {
    pub const LEN: usize = 8 + 32 + 32 + 16 + 8 + 8 + 8 + 1 + 1;
}

// ── Events / Errors ───────────────────────────────────────────────────────────

#[event]
pub struct HackathonCreated {
    pub hackathon_id: [u8; 16],
    pub organizer: Pubkey,
    pub prize_usdc: u64,
}

#[event]
pub struct PrizeReleased {
    pub hackathon_id: [u8; 16],
    pub prize_usdc: u64,
}

#[error_code]
pub enum EscrowError {
    #[msg("Not the organizer")]
    NotOrganizer,
    #[msg("Prize already released or refunded")]
    AlreadyReleased,
    #[msg("Winner shares exceed 100%")]
    InvalidShares,
    #[msg("Voting period has already started")]
    VotingAlreadyStarted,
    #[msg("Prize amount must be > 0")]
    InvalidPrize,
}
