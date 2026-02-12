import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
    isAgentEvent,
    parseAgentEvent,
    parseAgentStatusesResponse,
    parseApiErrorMessage,
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
                expect(() => parseAgentEvent(event)).not.toThrow();
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
        expect(() => parseAgentEvent(candidate)).toThrowError(
            'agent event.protocol_version must be v1.'
        );
    });

    it('rejects invalid state.update payload shape', () => {
        expect(() =>
            parseAgentEvent({
                id: 'evt_1',
                timestamp: new Date().toISOString(),
                thread_id: 'thread_1',
                run_id: 'run_1',
                seq_id: 1,
                protocol_version: 'v1',
                source: 'intent_extraction',
                type: 'state.update',
                data: {
                    summary: 123,
                },
            })
        ).toThrowError('agent event.data.summary must be a string.');
    });
});

describe('REST boundary parsers', () => {
    it('parses interrupt.request message payload from history', () => {
        const parsed = parseHistoryResponse([
            {
                id: 'm_interrupt_1',
                role: 'assistant',
                content: 'Please choose ticker',
                type: 'interrupt.request',
                data: {
                    type: 'ticker_selection',
                    title: 'Select ticker',
                    description: 'Multiple matches found',
                    data: {
                        options: ['AAPL', 'AAP'],
                    },
                    schema: {
                        type: 'object',
                    },
                },
            },
        ]);

        expect(parsed[0]?.type).toBe('interrupt.request');
        expect(parsed[0]?.data).toBeDefined();
    });

    it('rejects interrupt.request message without valid data payload', () => {
        expect(() =>
            parseHistoryResponse([
                {
                    id: 'm_interrupt_2',
                    role: 'assistant',
                    content: 'Please choose ticker',
                    type: 'interrupt.request',
                },
            ])
        ).toThrowError('history[0].data is required for interrupt.request.');
    });

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

    it('parses agent statuses response with strict status values', () => {
        const parsed = parseAgentStatusesResponse({
            current_node: 'intent_extraction',
            node_statuses: {
                intent_extraction: 'running',
                fundamental_analysis: 'done',
            },
            agent_outputs: {
                intent_extraction: {
                    summary: 'Extracting ticker',
                    preview: {
                        ticker: 'AAPL',
                    },
                },
            },
        });

        expect(parsed.current_node).toBe('intent_extraction');
        expect(parsed.node_statuses.intent_extraction).toBe('running');
        expect(parsed.agent_outputs.intent_extraction?.summary).toBe(
            'Extracting ticker'
        );
    });

    it('rejects unknown status in agent statuses response', () => {
        expect(() =>
            parseAgentStatusesResponse({
                node_statuses: {
                    intent_extraction: 'queued',
                },
                agent_outputs: {},
            })
        ).toThrowError(
            'agent statuses response.node_statuses.intent_extraction has unsupported status value.'
        );
    });

    it('extracts API error messages from string and validation formats', () => {
        expect(parseApiErrorMessage({ detail: 'Simple error' })).toBe('Simple error');
        expect(
            parseApiErrorMessage({
                detail: [
                    {
                        loc: ['body', 'thread_id'],
                        msg: 'Field required',
                        type: 'missing',
                    },
                ],
            })
        ).toBe('body.thread_id: Field required');
        expect(parseApiErrorMessage({ detail: [{ foo: 'bar' }] })).toBeNull();
    });
});
