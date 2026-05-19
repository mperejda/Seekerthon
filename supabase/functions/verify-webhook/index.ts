Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  return new Response(
    JSON.stringify({
      ok: false,
      detail:
        "verify-webhook is deprecated; winner state is finalized by the backend after on-chain claim/refund verification.",
    }),
    {
      status: 410,
      headers: { "Content-Type": "application/json" },
    },
  );
});
