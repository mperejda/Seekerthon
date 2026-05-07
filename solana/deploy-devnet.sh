#!/usr/bin/env bash
# Deploy Seekerthon programs to Solana devnet.
# Run inside Docker:  docker compose run --rm anchor ./deploy-devnet.sh
# Run locally:        ./deploy-devnet.sh  (requires anchor, solana CLI)
set -euo pipefail

# Ensure all tools are on PATH regardless of how the script is invoked
export PATH="/root/.local/share/solana/install/active_release/bin:$PATH"
export PATH="/root/.cargo/bin:$PATH"
export PATH="/root/.avm/bin:$PATH"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

KEYPAIR="${SOLANA_KEYPAIR:-$HOME/.config/solana/id.json}"
RPC="${SOLANA_RPC:-https://api.devnet.solana.com}"
MIN_SOL=2  # minimum SOL needed to cover deploy fees

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}   Seekerthon — Devnet Deploy${NC}"
echo -e "${CYAN}========================================${NC}"
echo -e "RPC    : ${CYAN}${RPC}${NC}"

# ── 1. Keypair ────────────────────────────────────────────────
if [ ! -f "$KEYPAIR" ]; then
    echo -e "${YELLOW}No keypair at $KEYPAIR — generating one now.${NC}"
    mkdir -p "$(dirname "$KEYPAIR")"
    solana-keygen new --outfile "$KEYPAIR" --no-bip39-passphrase
fi

solana config set --url "$RPC" --keypair "$KEYPAIR" > /dev/null
WALLET=$(solana address)
echo -e "Wallet : ${GREEN}$WALLET${NC}"

# ── 2. Balance check + airdrop ────────────────────────────────
BALANCE_SOL=$(solana balance | awk '{print $1}')
BALANCE_INT=${BALANCE_SOL%.*}

if [ "${BALANCE_INT:-0}" -lt "$MIN_SOL" ]; then
    echo -e "${YELLOW}Balance is ${BALANCE_SOL} SOL — requesting airdrop...${NC}"
    MAX_RETRIES=3
    for attempt in $(seq 1 $MAX_RETRIES); do
        if solana airdrop 2; then
            break
        fi
        if [ "$attempt" -eq "$MAX_RETRIES" ]; then
            echo -e "${RED}Airdrop failed after ${MAX_RETRIES} attempts. Fund manually:${NC}"
            echo "  solana airdrop 2 --url devnet"
            exit 1
        fi
        echo -e "${YELLOW}Airdrop attempt ${attempt} failed, retrying in 5s...${NC}"
        sleep 5
    done
fi

echo -e "Balance: ${GREEN}$(solana balance)${NC}"

# ── 3. Build ──────────────────────────────────────────────────
echo -e "\n${CYAN}Building programs...${NC}"
anchor build

# ── 4. Deploy ─────────────────────────────────────────────────
echo -e "\n${CYAN}Deploying to devnet...${NC}"
anchor deploy --provider.cluster devnet

# ── 5. Extract and validate program IDs ──────────────────────
VOTING_ID=$(anchor keys list 2>/dev/null | grep "^voting" | awk '{print $2}')
ESCROW_ID=$(anchor keys list 2>/dev/null | grep "^escrow" | awk '{print $2}')

# Validate extracted IDs look like base58 public keys (32–44 alphanumeric chars)
validate_pubkey() {
    local id="$1" name="$2"
    if [[ -z "$id" || ! "$id" =~ ^[1-9A-HJ-NP-Za-km-z]{32,44}$ ]]; then
        echo -e "${RED}ERROR: Could not extract valid program ID for '${name}' (got: '${id}')${NC}"
        exit 1
    fi
}
validate_pubkey "$VOTING_ID" "voting"
validate_pubkey "$ESCROW_ID" "escrow"

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}   Deploy complete${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Voting program : ${GREEN}${VOTING_ID}${NC}"
echo -e "Escrow program : ${GREEN}${ESCROW_ID}${NC}"

# ── 6. Patch backend/.env ─────────────────────────────────────
ENV_FILE="../backend/.env"
echo -e "\n${YELLOW}Add to backend/.env:${NC}"
echo "VOTING_PROGRAM_ID=${VOTING_ID}"
echo "ESCROW_PROGRAM_ID=${ESCROW_ID}"

upsert_env() {
    local key="$1" value="$2" file="$3"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

if [ -f "$ENV_FILE" ]; then
    echo -e "\n${YELLOW}Patching ${ENV_FILE} automatically...${NC}"
    upsert_env "VOTING_PROGRAM_ID" "$VOTING_ID" "$ENV_FILE"
    upsert_env "ESCROW_PROGRAM_ID" "$ESCROW_ID" "$ENV_FILE"
    echo -e "${GREEN}Done.${NC}"
fi
