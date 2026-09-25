const API = "/api/v1";

function encodeBase58(bytes: Uint8Array): string {
  const alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  let n = BigInt(0);
  for (const b of bytes) n = n * 256n + BigInt(b);
  let s = "";
  while (n > 0n) { s = alphabet[Number(n % 58n)] + s; n /= 58n; }
  for (const b of bytes) { if (b !== 0) break; s = "1" + s; }
  return s;
}

async function authRequest(path: string, options?: RequestInit) {
  const response = await fetch(API + path, {
    credentials: "include",
    cache: "no-store",
    signal: AbortSignal.timeout(30_000),
    ...options,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Sign-in failed (" + response.status + "). Please try again.");
  return data;
}

export async function authenticateWallet(
  walletAddress: string,
  signMessage: ((message: Uint8Array) => Promise<Uint8Array>) | undefined,
  isCancelled: () => boolean,
) {
  // A cookie is usable only when it belongs to the connected account.
  const session = await authRequest("/users/me").catch(() => null);
  if (isCancelled()) return null;
  if (session?.wallet_address === walletAddress) return session;
  if (!signMessage) throw new Error("This wallet cannot sign messages. Choose a wallet that supports message signing.");
  const challengeData = await authRequest("/users/challenge?wallet_address=" + walletAddress);
  if (isCancelled()) return null;
  const challenge = challengeData?.challenge;
  if (typeof challenge !== "string" || !challenge) throw new Error("Could not get a sign-in challenge. Please try again.");
  const signature = await signMessage(new TextEncoder().encode(challenge));
  if (isCancelled()) return null;
  const data = await authRequest("/users/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ wallet_address: walletAddress, signature: encodeBase58(signature), challenge }),
  });
  if (isCancelled()) return null;
  if (data?.user?.wallet_address !== walletAddress) throw new Error("Sign-in returned a different wallet. Please try again.");
  // Confirm the browser kept the cookie before enabling funding.
  const verified = await authRequest("/users/me");
  if (isCancelled()) return null;
  if (verified?.wallet_address !== walletAddress) throw new Error("Your wallet session could not be confirmed. Please retry sign-in.");
  return verified;
}
