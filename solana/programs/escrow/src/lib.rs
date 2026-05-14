use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token::{self, Mint, Token, TokenAccount, Transfer},
};
use solana_instructions_sysvar as instructions;

declare_id!("3kDfZk1hoB6VBg1By5JrmJ9jkKpog628a42W7hiRUNLJ");

const CLAIM_MESSAGE_PREFIX: &[u8] = b"seekerthon-claim:v1";
const ED25519_PROGRAM_ID: Pubkey = pubkey!("Ed25519SigVerify111111111111111111111111111");
const INSTRUCTIONS_SYSVAR_ID: Pubkey = pubkey!("Sysvar1nstructions1111111111111111111111111");

#[program]
pub mod escrow {
    use super::*;

    pub fn create_hackathon(
        ctx: Context<CreateHackathon>,
        hackathon_id: [u8; 16],
        prize_usdc: u64,
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
        escrow.usdc_mint = ctx.accounts.usdc_mint.key();
        escrow.platform_admin = ctx.accounts.platform_admin.key();
        escrow.hackathon_id = hackathon_id;
        escrow.prize_usdc = prize_usdc;
        escrow.voting_start = voting_start;
        escrow.voting_end = voting_end;
        escrow.project_count = 0;
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

    pub fn register_project(
        ctx: Context<RegisterProject>,
        project_id: [u8; 16],
    ) -> Result<()> {
        require!(
            ctx.accounts.hackathon_escrow.status == HackathonEscrowStatus::Active,
            EscrowError::AlreadyReleased,
        );
        require!(
            Clock::get()?.unix_timestamp < ctx.accounts.hackathon_escrow.voting_start,
            EscrowError::RegistrationClosed,
        );

        let record = &mut ctx.accounts.project_record;
        record.hackathon_escrow = ctx.accounts.hackathon_escrow.key();
        record.project_id = project_id;
        record.team_lead = ctx.accounts.team_lead.key();
        record.bump = ctx.bumps.project_record;

        let escrow = &mut ctx.accounts.hackathon_escrow;
        escrow.project_count = escrow
            .project_count
            .checked_add(1)
            .ok_or(EscrowError::Overflow)?;

        emit!(ProjectRegistered {
            hackathon_id: escrow.hackathon_id,
            project_id,
            team_lead: ctx.accounts.team_lead.key(),
        });

        Ok(())
    }

    pub fn claim_prize(
        ctx: Context<ClaimPrize>,
        _hackathon_id: [u8; 16],
        project_id: [u8; 16],
        prize_usdc: u64,
        expires_at: i64,
        nonce: [u8; 16],
    ) -> Result<()> {
        require!(
            ctx.accounts.hackathon_escrow.status == HackathonEscrowStatus::Active,
            EscrowError::AlreadyReleased,
        );
        require!(
            Clock::get()?.unix_timestamp >= ctx.accounts.hackathon_escrow.voting_end,
            EscrowError::VotingNotEnded,
        );
        require!(
            Clock::get()?.unix_timestamp <= expires_at,
            EscrowError::CertificateExpired,
        );
        require!(
            ctx.accounts.project_record.team_lead == ctx.accounts.winner.key(),
            EscrowError::InvalidProjectRecord,
        );
        require!(
            ctx.accounts.project_record.project_id == project_id,
            EscrowError::InvalidProjectRecord,
        );
        require!(
            ctx.accounts.hackathon_escrow.organizer != ctx.accounts.winner.key(),
            EscrowError::OrganizerCannotClaim,
        );
        require!(
            ctx.accounts.hackathon_escrow.prize_usdc == prize_usdc,
            EscrowError::InvalidPrize,
        );

        let prize = ctx.accounts.hackathon_escrow.prize_usdc;
        let message = claim_message(
            ctx.program_id,
            &ctx.accounts.hackathon_escrow.key(),
            &ctx.accounts.hackathon_escrow.hackathon_id,
            &project_id,
            &ctx.accounts.winner.key(),
            prize,
            expires_at,
            &nonce,
        );
        verify_ed25519_instruction(
            &ctx.accounts.instructions.to_account_info(),
            &ctx.accounts.hackathon_escrow.platform_admin,
            &message,
        )?;

        let bump = ctx.accounts.hackathon_escrow.bump;
        let hackathon_id = ctx.accounts.hackathon_escrow.hackathon_id;
        let seeds: &[&[u8]] = &[b"hackathon_escrow", hackathon_id.as_ref(), &[bump]];
        let signer_seeds = &[seeds];

        ctx.accounts.hackathon_escrow.status = HackathonEscrowStatus::Released;

        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.vault.to_account_info(),
                    to: ctx.accounts.winner_usdc_ata.to_account_info(),
                    authority: ctx.accounts.hackathon_escrow.to_account_info(),
                },
                signer_seeds,
            ),
            prize,
        )?;

        emit!(PrizeReleased {
            hackathon_id,
            prize_usdc: prize,
        });

        Ok(())
    }

    pub fn refund_escrow(
        ctx: Context<RefundEscrow>,
        _hackathon_id: [u8; 16],
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
            ctx.accounts.hackathon_escrow.project_count == 0,
            EscrowError::ProjectsRegistered,
        );

        let prize = ctx.accounts.hackathon_escrow.prize_usdc;
        let bump = ctx.accounts.hackathon_escrow.bump;
        let hackathon_id = ctx.accounts.hackathon_escrow.hackathon_id;
        let seeds: &[&[u8]] = &[b"hackathon_escrow", hackathon_id.as_ref(), &[bump]];
        let signer_seeds = &[seeds];

        ctx.accounts.hackathon_escrow.status = HackathonEscrowStatus::Released;

        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.vault.to_account_info(),
                    to: ctx.accounts.organizer_usdc_ata.to_account_info(),
                    authority: ctx.accounts.hackathon_escrow.to_account_info(),
                },
                signer_seeds,
            ),
            prize,
        )?;

        emit!(PrizeRefunded {
            hackathon_id,
            organizer: ctx.accounts.organizer.key(),
            prize_usdc: prize,
        });

        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(hackathon_id: [u8; 16])]
pub struct CreateHackathon<'info> {
    #[account(mut)]
    pub organizer: Signer<'info>,

    pub platform_admin: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = organizer,
        space = HackathonEscrow::LEN,
        seeds = [b"hackathon_escrow", hackathon_id.as_ref()],
        bump,
    )]
    pub hackathon_escrow: Account<'info, HackathonEscrow>,

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
#[instruction(project_id: [u8; 16])]
pub struct RegisterProject<'info> {
    #[account(mut)]
    pub team_lead: Signer<'info>,

    #[account(
        mut,
        seeds = [b"hackathon_escrow", hackathon_escrow.hackathon_id.as_ref()],
        bump = hackathon_escrow.bump,
    )]
    pub hackathon_escrow: Account<'info, HackathonEscrow>,

    #[account(
        init,
        payer = team_lead,
        space = ProjectRecord::LEN,
        seeds = [b"project", hackathon_escrow.key().as_ref(), project_id.as_ref()],
        bump,
    )]
    pub project_record: Account<'info, ProjectRecord>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(_hackathon_id: [u8; 16], project_id: [u8; 16])]
pub struct ClaimPrize<'info> {
    #[account(mut)]
    pub winner: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        mut,
        seeds = [b"hackathon_escrow", _hackathon_id.as_ref()],
        bump = hackathon_escrow.bump,
        has_one = usdc_mint @ EscrowError::InvalidMint,
    )]
    pub hackathon_escrow: Account<'info, HackathonEscrow>,

    #[account(
        seeds = [b"project", hackathon_escrow.key().as_ref(), project_id.as_ref()],
        bump = project_record.bump,
        has_one = hackathon_escrow @ EscrowError::InvalidProjectRecord,
    )]
    pub project_record: Account<'info, ProjectRecord>,

    #[account(
        mut,
        associated_token::mint = usdc_mint,
        associated_token::authority = hackathon_escrow,
    )]
    pub vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        associated_token::mint = usdc_mint,
        associated_token::authority = winner,
    )]
    pub winner_usdc_ata: Account<'info, TokenAccount>,

    /// CHECK: instructions sysvar is constrained by address and read only.
    #[account(address = INSTRUCTIONS_SYSVAR_ID)]
    pub instructions: AccountInfo<'info>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(_hackathon_id: [u8; 16])]
pub struct RefundEscrow<'info> {
    #[account(mut)]
    pub organizer: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        mut,
        seeds = [b"hackathon_escrow", _hackathon_id.as_ref()],
        bump = hackathon_escrow.bump,
        has_one = usdc_mint @ EscrowError::InvalidMint,
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
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, PartialEq)]
pub enum HackathonEscrowStatus {
    Active,
    Released,
}

#[account]
pub struct HackathonEscrow {
    pub organizer: Pubkey,
    pub usdc_mint: Pubkey,
    pub platform_admin: Pubkey,
    pub hackathon_id: [u8; 16],
    pub prize_usdc: u64,
    pub voting_start: i64,
    pub voting_end: i64,
    pub project_count: u32,
    pub status: HackathonEscrowStatus,
    pub bump: u8,
}

impl HackathonEscrow {
    pub const LEN: usize = 8 + 32 + 32 + 32 + 16 + 8 + 8 + 8 + 4 + 1 + 1;
}

#[account]
pub struct ProjectRecord {
    pub hackathon_escrow: Pubkey,
    pub project_id: [u8; 16],
    pub team_lead: Pubkey,
    pub bump: u8,
}

impl ProjectRecord {
    pub const LEN: usize = 8 + 32 + 16 + 32 + 1;
}

#[event]
pub struct HackathonCreated {
    pub hackathon_id: [u8; 16],
    pub organizer: Pubkey,
    pub prize_usdc: u64,
}

#[event]
pub struct ProjectRegistered {
    pub hackathon_id: [u8; 16],
    pub project_id: [u8; 16],
    pub team_lead: Pubkey,
}

#[event]
pub struct PrizeReleased {
    pub hackathon_id: [u8; 16],
    pub prize_usdc: u64,
}

#[event]
pub struct PrizeRefunded {
    pub hackathon_id: [u8; 16],
    pub organizer: Pubkey,
    pub prize_usdc: u64,
}

fn claim_message(
    program_id: &Pubkey,
    escrow: &Pubkey,
    hackathon_id: &[u8; 16],
    project_id: &[u8; 16],
    winner: &Pubkey,
    prize_usdc: u64,
    expires_at: i64,
    nonce: &[u8; 16],
) -> Vec<u8> {
    let mut msg = Vec::with_capacity(164);
    msg.extend_from_slice(CLAIM_MESSAGE_PREFIX);
    msg.extend_from_slice(program_id.as_ref());
    msg.extend_from_slice(escrow.as_ref());
    msg.extend_from_slice(hackathon_id);
    msg.extend_from_slice(project_id);
    msg.extend_from_slice(winner.as_ref());
    msg.extend_from_slice(&prize_usdc.to_le_bytes());
    msg.extend_from_slice(&expires_at.to_le_bytes());
    msg.extend_from_slice(nonce);
    msg
}

fn verify_ed25519_instruction(
    instructions_sysvar: &AccountInfo,
    expected_pubkey: &Pubkey,
    expected_message: &[u8],
) -> Result<()> {
    let current_index = instructions::load_current_index_checked(instructions_sysvar)? as usize;
    for i in 0..current_index {
        let ix = instructions::load_instruction_at_checked(i, instructions_sysvar)?;
        if ix.program_id.as_ref() != ED25519_PROGRAM_ID.as_ref() {
            continue;
        }
        if ix.data.len() < 16 || ix.data[0] != 1 {
            continue;
        }

        let sig_offset = u16::from_le_bytes([ix.data[2], ix.data[3]]) as usize;
        let sig_ix = u16::from_le_bytes([ix.data[4], ix.data[5]]);
        let pk_offset = u16::from_le_bytes([ix.data[6], ix.data[7]]) as usize;
        let pk_ix = u16::from_le_bytes([ix.data[8], ix.data[9]]);
        let msg_offset = u16::from_le_bytes([ix.data[10], ix.data[11]]) as usize;
        let msg_size = u16::from_le_bytes([ix.data[12], ix.data[13]]) as usize;
        let msg_ix = u16::from_le_bytes([ix.data[14], ix.data[15]]);

        if sig_ix != u16::MAX || pk_ix != u16::MAX || msg_ix != u16::MAX {
            continue;
        }
        if sig_offset + 64 > ix.data.len()
            || pk_offset + 32 > ix.data.len()
            || msg_offset + msg_size > ix.data.len()
        {
            continue;
        }
        if &ix.data[pk_offset..pk_offset + 32] != expected_pubkey.as_ref() {
            continue;
        }
        if &ix.data[msg_offset..msg_offset + msg_size] != expected_message {
            continue;
        }
        return Ok(());
    }

    err!(EscrowError::InvalidWinnerCertificate)
}

#[error_code]
pub enum EscrowError {
    #[msg("Not the organizer")]
    NotOrganizer,
    #[msg("Prize already released")]
    AlreadyReleased,
    #[msg("Prize amount must be > 0")]
    InvalidPrize,
    #[msg("voting_start must be >= 0 and voting_end must be > voting_start")]
    InvalidTimestamps,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Voting period has not ended yet")]
    VotingNotEnded,
    #[msg("Token mint does not match the escrow's registered mint")]
    InvalidMint,
    #[msg("Project registration has closed")]
    RegistrationClosed,
    #[msg("Winner certificate is invalid")]
    InvalidWinnerCertificate,
    #[msg("Winner certificate has expired")]
    CertificateExpired,
    #[msg("Project record does not match the claim")]
    InvalidProjectRecord,
    #[msg("Organizer cannot claim the prize")]
    OrganizerCannotClaim,
    #[msg("Cannot refund after projects have registered")]
    ProjectsRegistered,
}
