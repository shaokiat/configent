import { NextResponse } from "next/server";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ client_id: string; conversation_id: string }> }
) {
  const { client_id, conversation_id } = await params;
  const apiUrl = process.env.API_URL ?? "http://localhost:8000";

  const upstream = await fetch(
    `${apiUrl}/api/c/${client_id}/conversations/${conversation_id}`,
    { cache: "no-store" }
  );

  if (!upstream.ok) {
    return new NextResponse(null, { status: upstream.status });
  }

  const data = await upstream.json();
  return NextResponse.json(data);
}
