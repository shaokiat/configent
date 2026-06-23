import type { NextRequest } from "next/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ client_id: string }> }
) {
  const { client_id } = await params;
  const apiUrl = process.env.API_URL ?? "http://localhost:8000";

  const body = await request.text();

  const upstream = await fetch(`${apiUrl}/api/c/${client_id}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  if (!upstream.ok || !upstream.body) {
    return new Response("Upstream error", { status: upstream.status });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
