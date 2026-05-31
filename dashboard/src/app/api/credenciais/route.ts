import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NUTRIDEBY_API_URL || "http://api:8080";
const API_KEY = process.env.NUTRIDEBY_API_KEY || "";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${API_URL}/onboarding/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function GET() {
  const res = await fetch(`${API_URL}/onboarding/credentials/check`, {
    headers: { "X-API-Key": API_KEY },
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data);
}
