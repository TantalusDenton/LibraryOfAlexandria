import type { NextRequest } from "next/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const base = (process.env.API_URL || "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );
  const destination =
    base +
    "/" +
    path.map(encodeURIComponent).join("/") +
    request.nextUrl.search;
  const headers = new Headers();
  for (const key of [
    "content-type",
    "content-length",
    "cookie",
    "authorization",
    "origin",
    "last-event-id",
  ]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  try {
    const init: RequestInit & { duplex?: "half" } = {
      method: request.method,
      headers,
      cache: "no-store",
      signal: request.signal,
    };
    if (!["GET", "HEAD"].includes(request.method)) {
      init.body = request.body;
      init.duplex = "half";
    }
    const result = await fetch(destination, init);
    const output = new Headers();
    for (const key of [
      "content-type",
      "content-disposition",
      "set-cookie",
      "cache-control",
      "x-accel-buffering",
      "retry-after",
    ]) {
      const value = result.headers.get(key);
      if (value) output.set(key, value);
    }
    return new Response(result.body, {
      status: result.status,
      headers: output,
    });
  } catch {
    return Response.json(
      {
        detail:
          "The studio API is unavailable. Start the API service and try again.",
      },
      { status: 502 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
  proxy as OPTIONS,
};
