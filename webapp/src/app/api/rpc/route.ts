import { NextRequest, NextResponse } from "next/server";

const RPC_URL =
  process.env.HELIUS_RPC_URL ?? "https://api.mainnet-beta.solana.com";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const response = await fetch(RPC_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
