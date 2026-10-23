'use client';

import { useState } from 'react';

type ProbeResult = {
    route: string;
    startedAt: number;
    receivedAt: number[];
    ids: number[];
    terminal: boolean;
    headers: Record<string, string>;
};

type ReplayResult = {
    route: string;
    firstConnectionIds: number[];
    resumedIds: number[];
    combinedIds: number[];
    gapFree: boolean;
};

type AuthorizationResult = { route: string; status: number };

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://127.0.0.1:18100';

function parseFrame(frame: string): { id?: number; data?: string; event?: string } {
    const result: { id?: number; data?: string; event?: string } = {};
    for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('id:')) result.id = Number(line.slice(3).trim());
        if (line.startsWith('event:')) result.event = line.slice(6).trim();
        if (line.startsWith('data:')) result.data = line.slice(5).trimStart();
    }
    return result;
}

async function probe(route: string, count = 6, intervalMs?: number): Promise<ProbeResult> {
    const eventIntervalMs = intervalMs ?? Number(
        new URLSearchParams(window.location.search).get('probe_interval_ms') ?? '250',
    );
    const endpoint = route.includes('authenticated') ? 'authenticated'
        : route.includes('native') ? 'native'
            : 'manual';
    const via = route.split('-')[0];
    const routePath = via === 'direct'
        ? `${BACKEND_URL}/stream/${endpoint}`
        : via === 'proxy'
            ? `/api/proxy/${endpoint}`
            : `/rewrite/${endpoint}`;
    const url = new URL(routePath, window.location.href);
    url.searchParams.set('count', String(count));
    url.searchParams.set('interval_ms', String(eventIntervalMs));
    const startedAt = performance.now();
    const response = await fetch(url, { credentials: 'include' });
    if (!response.ok || !response.body) throw new Error(`${route}: HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const receivedAt: number[] = [];
    const ids: number[] = [];
    let buffer = '';
    let terminal = false;
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() ?? '';
        for (const frame of frames) {
            const parsed = parseFrame(frame);
            if (parsed.event === 'terminal') terminal = true;
            if (parsed.event === 'probe' && parsed.id !== undefined) {
                ids.push(parsed.id);
                receivedAt.push(performance.now() - startedAt);
            }
        }
    }
    return {
        route,
        startedAt,
        receivedAt,
        ids,
        terminal,
        headers: {
            contentType: response.headers.get('content-type') ?? '',
            cacheControl: response.headers.get('cache-control') ?? '',
            accelBuffering: response.headers.get('x-accel-buffering') ?? '',
            contentEncoding: response.headers.get('content-encoding') ?? '',
        },
    };
}

async function readIds(response: Response, stopAfter?: number): Promise<number[]> {
    if (!response.ok || !response.body) throw new Error(`stream: HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const ids: number[] = [];
    let buffer = '';
    while (ids.length < (stopAfter ?? Number.POSITIVE_INFINITY)) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() ?? '';
        for (const frame of frames) {
            const id = parseFrame(frame).id;
            if (id !== undefined) ids.push(id);
            if (stopAfter !== undefined && ids.length >= stopAfter) {
                await reader.cancel();
                return ids;
            }
        }
    }
    await reader.cancel();
    return ids;
}

async function replayProbe(route: string, endpoint: 'manual' | 'native'): Promise<ReplayResult> {
    const via = route.split('-')[0];
    const routeName = `${via}-${endpoint}`;
    const path = via === 'direct'
        ? `${BACKEND_URL}/stream/${endpoint}`
        : via === 'proxy'
            ? `/api/proxy/${endpoint}`
            : `/rewrite/${endpoint}`;
    const firstUrl = new URL(path, window.location.href);
    firstUrl.searchParams.set('count', '8');
    firstUrl.searchParams.set('interval_ms', '150');
    const firstConnectionIds = await readIds(
        await fetch(firstUrl, { credentials: 'include' }),
        3,
    );
    const resumeUrl = new URL(path, window.location.href);
    resumeUrl.searchParams.set('count', '8');
    resumeUrl.searchParams.set('interval_ms', '50');
    const resumedIds = await readIds(await fetch(resumeUrl, {
        credentials: 'include',
        headers: { 'Last-Event-ID': String(firstConnectionIds.at(-1)) },
    }));
    const combinedIds = [...firstConnectionIds, ...resumedIds];
    return {
        route: routeName,
        firstConnectionIds,
        resumedIds,
        combinedIds,
        gapFree: combinedIds.join(',') === '1,2,3,4,5,6,7,8',
    };
}

export default function Page() {
    const [results, setResults] = useState<ProbeResult[]>([]);
    const [replays, setReplays] = useState<ReplayResult[]>([]);
    const [authorization, setAuthorization] = useState<AuthorizationResult[]>([]);
    const [error, setError] = useState('');

    return (
        <main>
            <h1>SSE transport probe</h1>
            <p>Compare direct FastAPI, Next Route Handler proxy, and Next rewrite.</p>
            <button onClick={async () => {
                setError('');
                setResults([]);
                setReplays([]);
                setAuthorization([]);
                try {
                    const health: { native_sse?: boolean } = await fetch(`${BACKEND_URL}/health`).then((response) => response.json());
                    const availableRoutes = [
                        'direct', 'proxy', 'rewrite',
                        'direct-authenticated', 'proxy-authenticated', 'rewrite-authenticated',
                        ...(health.native_sse ? ['direct-native', 'proxy-native', 'rewrite-native'] : []),
                    ];
                    for (const route of availableRoutes) {
                        const result = await probe(route);
                        setResults((current) => [...current, result]);
                    }
            const replayEndpoints: ('manual' | 'native')[] = health.native_sse ? ['manual', 'native'] : ['manual'];
                    for (const endpoint of replayEndpoints) {
                for (const route of ['direct', 'proxy', 'rewrite']) {
                    const result = await replayProbe(route, endpoint);
                    setReplays((current) => [...current, result]);
                }
                    }
                    for (const [route, url] of [
                        ['direct', `${BACKEND_URL}/stream/authenticated?count=1`],
                        ['proxy', '/api/proxy/authenticated?count=1'],
                        ['rewrite', '/rewrite/authenticated?count=1'],
                    ]) {
                        const response = await fetch(url, { credentials: 'omit' });
                        setAuthorization((current) => [...current, { route, status: response.status }]);
                    }
                } catch (cause) {
                    setError(cause instanceof Error ? cause.message : String(cause));
                }
            }}>Run probe</button>
            <button onClick={async () => {
                setError('');
                try {
                    const result = await probe('direct', 10, 250);
                    setResults((current) => [...current, result]);
                } catch (cause) {
                    setError(cause instanceof Error ? cause.message : String(cause));
                }
            }}>Run direct stream</button>
            {error && <pre role="alert">{error}</pre>}
            <pre id="results" aria-live="polite">{JSON.stringify(results, null, 2)}</pre>
            <pre id="replays" aria-live="polite">{JSON.stringify(replays, null, 2)}</pre>
            <pre id="authorization" aria-live="polite">{JSON.stringify(authorization, null, 2)}</pre>
        </main>
    );
}
