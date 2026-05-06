// supabase/functions/verify-webhook/index.ts
// Triggered by backend when organizer verifies a winning project.
// Updates project status and sends FCM push notification.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.3";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const FCM_SERVER_KEY = Deno.env.get("FCM_SERVER_KEY") ?? "";

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const authHeader = req.headers.get("Authorization");
  if (authHeader !== `Bearer ${Deno.env.get("WEBHOOK_SECRET")}`) {
    return new Response("Unauthorized", { status: 401 });
  }

  const { hackathon_id, project_id, winner_wallet } = await req.json();

  // Mark project as winner
  await supabase
    .from("projects")
    .update({ status: "winner" })
    .eq("id", project_id);

  // Mark hackathon completed
  await supabase
    .from("hackathons")
    .update({ status: "completed" })
    .eq("id", hackathon_id);

  // Fetch all voters of this project to notify
  const { data: votes } = await supabase
    .from("votes")
    .select("voter_id, users(wallet_address)")
    .eq("project_id", project_id);

  // Send FCM push notification (optional — requires FCM setup)
  if (FCM_SERVER_KEY && votes) {
    const hackathon = await supabase
      .from("hackathons")
      .select("title")
      .eq("id", hackathon_id)
      .single();

    const project = await supabase
      .from("projects")
      .select("name")
      .eq("id", project_id)
      .single();

    const notification = {
      notification: {
        title: "Winner announced!",
        body: `${project.data?.name} won ${hackathon.data?.title}!`,
      },
      condition: `'hackathon_${hackathon_id}' in topics`,
    };

    await fetch("https://fcm.googleapis.com/fcm/send", {
      method: "POST",
      headers: {
        Authorization: `key=${FCM_SERVER_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(notification),
    });
  }

  return new Response(JSON.stringify({ ok: true }), {
    headers: { "Content-Type": "application/json" },
  });
});
