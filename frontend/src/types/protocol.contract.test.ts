import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
    isAgentEvent,
    parseHistoryResponse,
    parseStreamStartResponse,
    parseThreadStateResponse,
} from './protocol';

interface FixtureManifestEntry {
    version: string;
    fixture: string;
}

interface FixtureManifest {
    supported_versions: FixtureManifestEntry[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

const locateFixturesDir = (): string => {
    const candidates = [
        path.resolve(process.cwd(), '../contracts/fixtures'),
        path.resolve(process.cwd(), 'contracts/fixtures'),
    ];
    const fixturesDir = candidates.find((candidate) => fs.existsSync(candidate));
    if (!fixturesDir) throw new Error('Unable to locate contracts/fixtures directory.');
    return fixturesDir;
};

const loadManifest = (fixturesDir: string): FixtureManifest => {
    const manifestPath = path.join(fixturesDir, 'manifest.json');
    const raw: unknown = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    if (!isRecord(raw) || !Array.isArray(raw.supported_versions)) {
        throw new Error('Invalid fixture manifest format.');
    }
    const supported_versions = raw.supported_versions.map((entry, index) => {
        if (!isRecord(entry)) {
            throw new Error(`Invalid manifest entry at index ${index}.`);
        }
        if (typeof entry.version !== 'string' || typeof entry.fixture !== 'string') {
            throw new Error(`Invalid manifest entry fields at index ${index}.`);
        }
        return {
            version: entry.version,
            fixture: entry.fixture,
        };
    });
    return { supported_versions };
};

const loadFixtureEvents = (fixturesDir: string, fixtureName: string): unknown[] => {
    const fixturePath = path.join(fixturesDir, fixtureName);
    const raw: unknown = JSON.parse(fs.readFileSync(fixturePath, 'utf-8'));
    if (!Array.isArray(raw)) {
        throw new Error(`Fixture ${fixtureName} must be an array.`);
    }
    return raw;
};

describe('SSE contract fixtures', () => {
    it('should accept all supported v1 fixture events', () => {
        const fixturesDir = locateFixturesDir();
        const manifest = loadManifest(fixturesDir);
        expect(manifest.supported_versions.length).toBeGreaterThan(0);

        const v1Entries = manifest.supported_versions.filter((entry) => entry.version === 'v1');
        expect(v1Entries.length).toBeGreaterThan(0);

        for (const entry of v1Entries) {
            const events = loadFixtureEvents(fixturesDir, entry.fixture);
            expect(events.length).toBeGreaterThan(0);
            for (const event of events) {
                expect(isAgentEvent(event)).toBe(true);
            }
        }
    });

    it('should reject unknown protocol versions', () => {
        const fixturesDir = locateFixturesDir();
        const manifest = loadManifest(fixturesDir);
        const v1Entry = manifest.supported_versions.find((entry) => entry.version === 'v1');
        if (!v1Entry) throw new Error('No v1 fixture entry found in manifest.');
        const events = loadFixtureEvents(fixturesDir, v1Entry.fixture);
        const first = events[0];
        expect(isAgentEvent(first)).toBe(true);
        if (!isRecord(first)) throw new Error('Fixture event must be an object.');

        const candidate = { ...first, protocol_version: 'v2' };
        expect(isAgentEvent(candidate)).toBe(false);
    });
});

describe('REST boundary parsers', () => {
    it('rejects unknown history message type', () => {
        expect(() =>
            parseHistoryResponse([
                {
                    id: 'm1',
                    role: 'assistant',
                    content: 'hello',
                    type: 'custom_type',
                },
            ])
        ).toThrowError(
            'history[0].type must be one of text | financial_report | interrupt.request.'
        );
    });

    it('parses thread state with strict valid status values', () => {
        const parsed = parseThreadStateResponse({
            thread_id: 'thread_1',
            messages: [
                {
                    id: 'm1',
                    role: 'assistant',
                    content: 'done',
                    type: 'text',
                },
            ],
            interrupts: [
                {
                    type: 'ticker_selection',
                    reason: 'Ambiguous ticker',
                    candidates: [
                        {
                            symbol: 'AAPL',
                            name: 'Apple Inc.',
                            confidence: 0.95,
                        },
                    ],
                    intent: {
                        is_valuation_request: true,
                        reasoning: 'User asks for valuation',
                        ticker: 'AAPL',
                    },
                },
            ],
            resolved_ticker: 'AAPL',
            status: 'done',
            next: null,
            is_running: false,
            node_statuses: {
                intent_extraction: 'done',
                fundamental_analysis: 'running',
            },
            agent_outputs: {
                intent_extraction: {
                    summary: 'Ticker resolved',
                    preview: { ticker: 'AAPL' },
                    reference: null,
                },
            },
            last_seq_id: 12,
        });

        expect(parsed.thread_id).toBe('thread_1');
        expect(parsed.node_statuses.intent_extraction).toBe('done');
        expect(parsed.node_statuses.fundamental_analysis).toBe('running');
        expect(parsed.agent_outputs.intent_extraction?.summary).toBe('Ticker resolved');
    });

    it('rejects unknown node status values', () => {
        expect(() =>
            parseThreadStateResponse({
                thread_id: 'thread_1',
                messages: [
                    {
                        id: 'm1',
                        role: 'assistant',
                        content: 'done',
                        type: 'text',
                    },
                ],
                interrupts: [],
                is_running: false,
                node_statuses: {
                    unknown_agent: 'unexpected_status',
                },
                agent_outputs: {},
                last_seq_id: 1,
            })
        ).toThrowError('thread.node_statuses.unknown_agent has unsupported status value.');
    });

    it('rejects null exchange in ticker candidate under zero-compat mode', () => {
        expect(() =>
            parseThreadStateResponse({
                thread_id: 'thread_1',
                messages: [
                    {
                        id: 'm1',
                        role: 'assistant',
                        content: 'done',
                        type: 'text',
                    },
                ],
                interrupts: [
                    {
                        type: 'ticker_selection',
                        reason: 'Ambiguous ticker',
                        candidates: [
                            {
                                symbol: 'AAPL',
                                name: 'Apple Inc.',
                                confidence: 0.95,
                                exchange: null,
                            },
                        ],
                    },
                ],
                is_running: false,
                node_statuses: {
                    intent_extraction: 'done',
                },
                agent_outputs: {},
                last_seq_id: 1,
            })
        ).toThrowError('thread.interrupts[0].candidates[0].exchange must be a string | undefined.');
    });

    it('rejects invalid thread state payload', () => {
        expect(() =>
            parseThreadStateResponse({
                thread_id: 'thread_1',
                messages: [],
                interrupts: [],
                is_running: false,
                node_statuses: [],
                agent_outputs: {},
                last_seq_id: 1,
            })
        ).toThrowError('thread response.node_statuses must be an object.');
    });

    it('parses stream start response and rejects invalid status', () => {
        const parsed = parseStreamStartResponse({
            status: 'started',
            thread_id: 'thread_2',
        });
        expect(parsed.status).toBe('started');

        expect(() =>
            parseStreamStartResponse({
                status: 'queued',
                thread_id: 'thread_2',
            })
        ).toThrowError('stream start response.status must be started or running.');
    });
});
