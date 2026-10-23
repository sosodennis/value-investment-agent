type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, context: RouteContext): Promise<Response> {
    const { path } = await context.params;
    const backend = process.env.SSE_BACKEND_URL ?? 'http://127.0.0.1:18100';
    const incoming = new URL(request.url);
    const upstreamPath = path[0] === 'health' ? '/health' : `/stream/${path.join('/')}`;
    const upstreamUrl = new URL(`${upstreamPath}${incoming.search}`, backend);
    const forwardedHeaders = new Headers();
    for (const name of ['cookie', 'last-event-id', 'x-request-id', 'traceparent']) {
        const value = request.headers.get(name);
        if (value) forwardedHeaders.set(name, value);
    }
    const upstream = await fetch(upstreamUrl, {
        method: 'GET',
        headers: forwardedHeaders,
        signal: request.signal,
        cache: 'no-store',
    });
    const headers = new Headers();
    for (const key of ['content-type', 'cache-control', 'x-accel-buffering', 'content-encoding']) {
        const value = upstream.headers.get(key);
        if (value) headers.set(key, value);
    }
    return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers,
    });
}
