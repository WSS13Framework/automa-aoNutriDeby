import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NUTRIDEBY_API_URL || "http://api:8080";
const API_KEY = process.env.NUTRIDEBY_API_KEY || "";

export async function GET(
  _: NextRequest,
  { params }: { params: { jobId: string } }
) {
  try {
    const res = await fetch(`${API_URL}/onboarding/sync/status/${params.jobId}`, {
      headers: { "X-API-Key": API_KEY },
      cache: "no-store",
    });
    const contentType = res.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      return NextResponse.json(
        { error: "upstream_error", detail: await res.text() },
        { status: res.status }
      );
    }
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    return NextResponse.json({ error: "fetch_failed", detail: err.message }, { status: 502 });
  }
}
