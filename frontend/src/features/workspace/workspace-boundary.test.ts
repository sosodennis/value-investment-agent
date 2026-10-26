import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const featureRoot = dirname(fileURLToPath(import.meta.url));

function productionSources(directory: string): string[] {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return productionSources(path);
        if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) {
            return [];
        }
        return [path];
    });
}

describe('workspace feature boundaries', () => {
    it('does not import retired workspace or agent-output presentation components', () => {
        const imports = productionSources(featureRoot).flatMap((path) => {
            const source = readFileSync(path, 'utf8');
            return [...source.matchAll(/from\s+['"]([^'"]+)['"]/g)].map(
                ([, specifier]) => ({ path, specifier })
            );
        });

        expect(
            imports.filter(({ specifier }) =>
                specifier.includes('/components/workspace/') ||
                specifier.includes('/components/agent-outputs/')
            )
        ).toEqual([]);
    });
});
