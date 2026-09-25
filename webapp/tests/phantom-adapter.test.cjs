const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const { PublicKey, Transaction } = require("@solana/web3.js");

const code = ts.transpileModule(
  fs.readFileSync(path.join(__dirname, "../src/lib/phantom-adapter.ts"), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } },
).outputText;

function provider(name, prompts) {
  const listeners = new Map();
  return {
    name, isPhantom: true, publicKey: new PublicKey(new Uint8Array(32).fill(1)),
    async connect() { prompts.push(this.name + ":connect"); },
    async disconnect() { prompts.push(this.name + ":disconnect"); },
    async signMessage() {
      prompts.push(this.name + ":message");
      return { signature: new Uint8Array(64) };
    },
    async signTransaction(tx) { prompts.push(this.name + ":transaction"); return tx; },
    on(event, fn) { listeners.set(event, fn); },
    removeListener(event) { listeners.delete(event); },
    emit(event, value) { listeners.get(event)?.(value); },
  };
}

function setup(browser) {
  const context = { exports: {}, require, window: browser };
  vm.runInNewContext(code, context);
  return context.exports;
}

test("Phantom connect, login signing, and escrow signing never invoke Backpack's shared provider", async () => {
  const prompts = [];
  const phantom = provider("Phantom", prompts);
  const backpack = provider("Backpack", prompts);
  // Reproduce a browser with Backpack owning window.solana, including its
  // compatibility isPhantom flag, while both extensions are installed.
  const browser = { phantom: { solana: phantom }, solana: backpack, backpack };
  const { PhantomAdapter } = setup(browser);
  const adapter = new PhantomAdapter();
  await adapter.connect();
  await adapter.signMessage(new Uint8Array([1]));
  const tx = new Transaction();
  assert.equal(await adapter.signTransaction(tx), tx);
  await adapter.disconnect();
  assert.deepEqual(prompts, ["Phantom:connect", "Phantom:message", "Phantom:transaction", "Phantom:disconnect"]);
});

test("missing Phantom fails instead of falling back to Backpack", async () => {
  const prompts = [];
  const { PhantomAdapter } = setup({ solana: provider("Backpack", prompts) });
  await assert.rejects(new PhantomAdapter().connect(), /Phantom is not available/);
  assert.deepEqual(prompts, []);
});

test("Backpack advertising Phantom compatibility is never accepted as Phantom", async () => {
  const prompts = [];
  const backpack = { ...provider("Backpack", prompts), isBackpack: true };
  const { PhantomAdapter } = setup({ phantom: { solana: backpack }, solana: backpack });
  await assert.rejects(new PhantomAdapter().connect(), /Phantom is not available/);
  assert.deepEqual(prompts, []);
});

test("signing stays pinned to the provider used to connect", async () => {
  const prompts = [];
  const browser = { phantom: { solana: provider("Phantom", prompts) } };
  const { PhantomAdapter } = setup(browser);
  const adapter = new PhantomAdapter();
  await adapter.connect();
  browser.phantom.solana = provider("Replacement", prompts);
  await adapter.signMessage(new Uint8Array());
  await adapter.signTransaction(new Transaction());
  assert.deepEqual(prompts, ["Phantom:connect", "Phantom:message", "Phantom:transaction"]);
});

test("account changes and disconnects update adapter state", async () => {
  const phantom = provider("Phantom", []);
  const { PhantomAdapter } = setup({ phantom: { solana: phantom } });
  const adapter = new PhantomAdapter();
  await adapter.connect();
  const nextAccount = new PublicKey(new Uint8Array(32).fill(2));
  phantom.emit("accountChanged", nextAccount);
  assert.equal(adapter.publicKey.toBase58(), nextAccount.toBase58());
  phantom.emit("disconnect");
  assert.equal(adapter.connected, false);
  await assert.rejects(adapter.signMessage(new Uint8Array()));
});

test("the original wallet menu keeps Backpack and other wallets and only one Phantom entry", () => {
  const { preferredWallets, DIRECT_PHANTOM } = setup({});
  const wallets = ["Phantom", DIRECT_PHANTOM, "Backpack", "Solflare"].map((name) => ({ adapter: { name } }));
  assert.deepEqual(preferredWallets(wallets).map(({ adapter }) => adapter.name), [
    DIRECT_PHANTOM, "Backpack", "Solflare",
  ]);
});
