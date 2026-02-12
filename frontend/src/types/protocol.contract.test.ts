import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { isAgentEvent } from './protocol';

interface FixtureManifestEntry {
    version: string;
    fixture: string;
}

interface FixtureManifest {
    supported_versions: FixtureManifestEntry[];
}

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
    const raw = JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as unknown;
    if (!raw || typeof raw !== 'object' || !Array.isArray((raw as { supported_versions?: unknown[] }).supported_versions)) {
        throw new Error('Invalid fixture manifest format.');
    }
    return raw as FixtureManifest;
};

const loadFixtureEvents = (fixturesDir: string, fixtureName: string): unknown[] => {
    const fixturePath = path.join(fixturesDir, fixtureName);
    const raw = JSON.parse(fs.readFileSync(fixturePath, 'utf-8')) as unknown;
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

        const candidate = { ...(first as Record<string, unknown>), protocol_version: 'v2' };
        expect(isAgentEvent(candidate)).toBe(false);
    });
});
