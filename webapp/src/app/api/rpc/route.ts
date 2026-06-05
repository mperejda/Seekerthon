import { NextRequest, NextResponse } from "next/server";

const RPC_URL = process.env.SOLANA_RPC_URL;

export async function POST(request: NextRequest) {
  if (!RPC_URL) {
    return NextResponse.json(
      {
        error:
          "Solana RPC proxy is not configured. Set SOLANA_RPC_URL to a mainnet RPC endpoint.",
      },
      { status: 500 }
    );
  }

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
