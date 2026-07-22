import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import {
  keypairIdentity,
  generateSigner,
  percentAmount,
} from "@metaplex-foundation/umi";
import { createTree, mplBubblegum } from "@metaplex-foundation/mpl-bubblegum";
import {
  createNft,
  mplTokenMetadata,
} from "@metaplex-foundation/mpl-token-metadata";

const RPC_URL = process.env.RPC_URL;
const KEYPAIR_JSON = process.env.AUTHORITY_KEYPAIR;

if (!RPC_URL) throw new Error("RPC_URL env var required (your Helius URL)");
if (!KEYPAIR_JSON) throw new Error("AUTHORITY_KEYPAIR env var required (JSON byte array from Railway)");

const umi = createUmi(RPC_URL).use(mplBubblegum()).use(mplTokenMetadata());

const keypairBytes = new Uint8Array(JSON.parse(KEYPAIR_JSON));
const authority = umi.eddsa.createKeypairFromSecretKey(keypairBytes);
umi.use(keypairIdentity(authority));

console.log("Authority:", authority.publicKey);
console.log("");

// ── Step 1: Create Merkle tree ────────────────────────────────────────────
// depth=14 → 16,384 leaves; canopy=8 keeps tx size manageable; ~0.34 SOL
console.log("Creating Merkle tree (depth=14, canopy=8)...");
const merkleTree = generateSigner(umi);
await (
  await createTree(umi, {
    merkleTree,
    maxDepth: 14,
    maxBufferSize: 64,
    canopyDepth: 8,
  })
).sendAndConfirm(umi, { confirm: { commitment: "finalized" } });

console.log("✓ Merkle tree created");
console.log("  SUPPORT_NFT_TREE_ADDRESS =", merkleTree.publicKey);
console.log("");

// ── Step 2: Create collection NFT ────────────────────────────────────────
console.log("Creating collection NFT...");
const collectionMint = generateSigner(umi);
await createNft(umi, {
  mint: collectionMint,
  name: "Seekerthon Builder Support",
  symbol: "BSUP",
  uri: "https://pub-1568addf02304956adde8ae0cb8c69b8.r2.dev/images/support-nft.png",
  sellerFeeBasisPoints: percentAmount(5),
  isCollection: true,
}).sendAndConfirm(umi, { confirm: { commitment: "finalized" } });

console.log("✓ Collection NFT created");
console.log("  SUPPORT_NFT_COLLECTION_MINT =", collectionMint.publicKey);
console.log("");

console.log("── Set these in Railway ──────────────────────────────────────");
console.log(`SUPPORT_NFT_TREE_ADDRESS=${merkleTree.publicKey}`);
console.log(`SUPPORT_NFT_COLLECTION_MINT=${collectionMint.publicKey}`);
