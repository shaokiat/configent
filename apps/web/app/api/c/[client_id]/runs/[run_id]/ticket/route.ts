import { NextResponse } from "next/server";

// Confirms the ticket a support-graph turn proposed. Deliberately forwards no request body:
// the draft lives in the run's checkpoint server-side, so a caller can accept an offer but
// cannot author a ticket of its own.
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ client_id: string; run_id: string }> }
) {
  const { client_id, run_id } = await params;
  const apiUrl = process.env.API_URL ?? "http://localhost:8000";

  const upstream = await fetch(`${apiUrl}/api/c/${client_id}/runs/${run_id}/ticket`, {
    method: "POST",
    cache: "no-store",
  });

  if (!upstream.ok) {
    return new NextResponse(null, { status: upstream.status });
  }

  return NextResponse.json(await upstream.json());
}
