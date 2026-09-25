const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

// Run the browser-independent auth flow without a wallet extension or live funds.
const code = ts.transpileModule(
  fs.readFileSync(path.join(__dirname, "../src/lib/wallet-auth.ts"), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } },
).outputText;

function setup(responses) {
  const calls = [];
  const context = {
    exports: {}, TextEncoder, AbortSignal,
    fetch: async (url, options) => {
      calls.push({ url, options });
      assert.ok(url.startsWith("/api/v1/"), "authentication must stay same-origin");
      assert.equal(options.credentials, "include");
      assert.equal(options.cache, "no-store");
      assert.ok(responses.length, "unexpected request: " + url);
      const next = responses.shift();
      return { ok: next.status < 400, status: next.status, json: async () => next.body };
    },
  };
  vm.runInNewContext(code, context);
  return {
    authenticate: context.exports.authenticateWallet,
    restore: context.exports.restoreWalletSession,
    signer: context.exports.selectedWalletSigner,
    calls,
  };
}
const wallet = "organizer-wallet";
const user = { id: "organizer", wallet_address: wallet };
const ok = (body) => ({ status: 200, body });
const noSession = () => ({ status: 401, body: { detail: "Missing auth token" } });
const challenge = () => ok({ challenge: "wallet-bound-challenge" });
const signature = async () => new Uint8Array([0, 1]);
const active = () => false;

test("restores only a matching cookie without prompting", async () => {
  const { authenticate, calls } = setup([ok(user)]);
  const result = await authenticate(wallet, () => assert.fail("must not prompt"), active);
  assert.equal(result.wallet_address, wallet);
  assert.equal(calls.length, 1);
});

test("signs in a switched wallet and verifies its cookie", async () => {
  const { authenticate, calls } = setup([
    ok({ id: "other", wallet_address: "other-wallet" }),
    challenge(), ok({ user }), ok(user),
  ]);
  const result = await authenticate(wallet, async (message) => {
    assert.equal(new TextDecoder().decode(message), "wallet-bound-challenge");
    return signature();
  }, active);
  assert.equal(result.wallet_address, wallet);
  assert.deepEqual(JSON.parse(calls[2].options.body), {
    wallet_address: wallet, signature: "12", challenge: "wallet-bound-challenge",
  });
});

test("a rejected signature can be retried with the same wallet", async () => {
  const { authenticate, calls } = setup([
    noSession(), challenge(), noSession(), challenge(), ok({ user }), ok(user),
  ]);
  await assert.rejects(authenticate(wallet, async () => { throw new Error("User rejected"); }, active), /User rejected/);
  assert.equal((await authenticate(wallet, signature, active)).wallet_address, wallet);
  assert.equal(calls.filter((call) => call.url.endsWith("/login")).length, 1);
});

test("disconnect during a signature never submits the previous wallet login", async () => {
  let cancelled = false;
  const { authenticate, calls } = setup([noSession(), challenge()]);
  const result = await authenticate(wallet, async () => {
    cancelled = true;
    return signature();
  }, () => cancelled);
  assert.equal(result, null);
  assert.equal(calls.length, 2);
});

test("failed challenge is surfaced without requesting a signature", async () => {
  const { authenticate } = setup([noSession(), { status: 503, body: { detail: "Please try again later" } }]);
  await assert.rejects(authenticate(wallet, () => assert.fail("must not prompt"), active), /Please try again later/);
});

test("missing cookie after login does not enable funding", async () => {
  const { authenticate } = setup([noSession(), challenge(), ok({ user }), noSession()]);
  await assert.rejects(authenticate(wallet, signature, active), /Missing auth token/);
});

test("a late response after an account switch is ignored", async () => {
  const { authenticate, calls } = setup([ok(user)]);
  assert.equal(await authenticate(wallet, signature, () => true), null);
  assert.equal(calls.length, 1);
});

test("unsupported message signing gives an actionable error", async () => {
  const { authenticate } = setup([noSession()]);
  await assert.rejects(authenticate(wallet, undefined, active), /cannot sign messages/);
});

test("automatic session restore never starts a signing challenge", async () => {
  const { restore, calls } = setup([noSession(), ok({ id: "other", wallet_address: "other-wallet" }), ok(user)]);
  assert.equal(await restore(wallet), null);
  assert.equal(await restore(wallet), null);
  assert.equal((await restore(wallet)).wallet_address, wallet);
  assert.ok(calls.every(({ url }) => url.endsWith("/users/me")));
});

for (const name of ["Phantom", "Backpack", "Another Wallet Standard wallet"]) {
  test(name + " selection signs only through that adapter", async () => {
    const { authenticate, signer } = setup([noSession(), challenge(), ok({ user }), ok(user)]);
    const prompts = [];
    const adapters = ["Phantom", "Backpack", "Another Wallet Standard wallet"].map((name) => ({
      name,
      connected: true,
      publicKey: { toBase58: () => wallet },
      async signMessage() {
        // Accessing this.name also verifies the adapter's receiver is preserved.
        prompts.push(this.name);
        return signature();
      },
    }));
    const selected = adapters.find((adapter) => adapter.name === name);
    await authenticate(wallet, signer(selected, wallet, () => true), active);
    assert.deepEqual(prompts, [name]);
  });
}

test("switching adapters with the same public key cancels the previous signer", async () => {
  const { signer } = setup([]);
  let current = true;
  const sign = signer({
    connected: true,
    publicKey: { toBase58: () => wallet },
    signMessage: () => assert.fail("old wallet must not open"),
  }, wallet, () => current);
  current = false;
  await assert.rejects(sign(new Uint8Array()), /selected wallet changed/);
});

test("an account change inside the adapter cancels signing before React updates", async () => {
  const { signer } = setup([]);
  const adapter = {
    connected: true,
    publicKey: { toBase58: () => wallet },
    signMessage: () => assert.fail("old account must not sign"),
  };
  const sign = signer(adapter, wallet, () => true);
  adapter.publicKey = { toBase58: () => "new-account" };
  await assert.rejects(sign(new Uint8Array()), /selected wallet changed/);
});

test("switching wallets while approval is pending discards the signature", async () => {
  const { authenticate, signer, calls } = setup([noSession(), challenge()]);
  let current = true;
  const sign = signer({
    connected: true,
    publicKey: { toBase58: () => wallet },
    async signMessage() {
      current = false;
      return signature();
    },
  }, wallet, () => current);
  await assert.rejects(authenticate(wallet, sign, active), /selected wallet changed/);
  assert.ok(calls.every(({ url }) => !url.endsWith("/login")));
});
