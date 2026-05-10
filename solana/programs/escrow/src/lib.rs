use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token::{self, Mint, Token, TokenAccount, Transfer},
};

declare_id!("GCiJViWButEvTMgRb1HMfJLDYU3ceKyNHvjWQXMUEGxs");

#[program]
pub mod escrow {
    use super::*;

    pub fn create_hackathon(
        ctx: Context<CreateHackathon>,
        hackathon_id: [u8; 16],
        prize_usdc: u64,   // base units (1 USDC = 1_000_000)
        voting_start: i64,
        voting_end: i64,
    ) -> Result<()> {
        require!(prize_usdc > 0, EscrowError::InvalidPrize);
        require!(
            voting_start >= 0 && voting_end > voting_start,
            EscrowError::InvalidTimestamps,
        );

        let escrow = &mut ctx.accounts.hackathon_escrow;
        escrow.organizer = ctx.accounts.organizer.key();
        escrow.hackathon_id = hackathon_id;
        escrow.prize_usdc = prize_usdc;
        escrow.usdc_mint = ctx.accounts.usdc_mint.key();
        escrow.voting_start = voting_start;
        escrow.voting_end = voting_end;
        escrow.status = HackathonEscrowStatus::Active;
        escrow.bump = ctx.bumps.hackathon_escrow;

        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.key(),
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

    pub fn release_prize<'info>(
        ctx: Context<'info, ReleasePrize<'info>>,
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
        require!(
            Clock::get()?.unix_timestamp >= ctx.accounts.hackathon_escrow.voting_end,
            EscrowError::VotingNotEnded,
        );
        require!(
            ctx.remaining_accounts.len() == winner_share_bps.len(),
            EscrowError::RecipientCountMismatch,
        );

        require!(!winner_share_bps.is_empty(), EscrowError::InvalidShares);
        let total_bps: u32 = winner_share_bps.iter().map(|&b| b as u32).sum();
        require!(total_bps == 10_000, EscrowError::InvalidShares);

        let prize = ctx.accounts.hackathon_escrow.prize_usdc;
        let bump = ctx.accounts.hackathon_escrow.bump;
        let usdc_mint_key = ctx.accounts.usdc_mint.key();
        let seeds: &[&[u8]] = &[b"hackathon_escrow", hackathon_id.as_ref(), &[bump]];
        let signer_seeds = &[seeds];

        let vault_info = ctx.accounts.vault.to_account_info();
        let authority_info = ctx.accounts.hackathon_escrow.to_account_info();
        let token_program_key = ctx.accounts.token_program.key();

        for (i, recipient_ata) in ctx.remaining_accounts.iter().enumerate() {
            // Validate owner (catches non-token accounts) then check mint via accessor
            // so wrong-mint ATAs are rejected with a clear error before the CPI fires.
            require!(
                recipient_ata.owner == &anchor_spl::token::ID,
                EscrowError::InvalidRecipientAccount,
            );
            let acct_mint = anchor_spl::token::accessor::mint(recipient_ata)
                .map_err(|_| EscrowError::InvalidRecipientAccount)?;
            require!(acct_mint == usdc_mint_key, EscrowError::InvalidRecipientMint);

            let share_bps = winner_share_bps[i] as u64;
            let amount = prize
                .checked_mul(share_bps)
                .ok_or(EscrowError::Overflow)?
                / 10_000;

            if amount == 0 {
                continue;
            }

            token::transfer(
                CpiContext::new_with_signer(
                    token_program_key,
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
    // Winner USDC ATAs passed in remaining_accounts; validated in instruction body.
}

// ── State ──────────────────────────────────────────────────────────────────────

#[derive(AnchorSerialize, AnchorDeserialize, Clone, PartialEq)]
pub enum HackathonEscrowStatus {
    Active,
    Released,
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
    #[msg("Prize already released")]
    AlreadyReleased,
    #[msg("Winner shares exceed 100%")]
    InvalidShares,
    #[msg("Prize amount must be > 0")]
    InvalidPrize,
    #[msg("voting_start must be >= 0 and voting_end must be > voting_start")]
    InvalidTimestamps,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Recipient account is not a valid token account")]
    InvalidRecipientAccount,
    #[msg("Recipient token account mint does not match USDC mint")]
    InvalidRecipientMint,
    #[msg("Number of recipients must match number of share entries")]
    RecipientCountMismatch,
    #[msg("Voting period has not ended yet")]
    VotingNotEnded,
}
