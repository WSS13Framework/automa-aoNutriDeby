import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NUTRIDEBY_API_URL || "http://api:8080";

export async function POST(req: NextRequest) {
  const body = await req.json();

  const res = await fetch(`${API_URL}/onboarding/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
