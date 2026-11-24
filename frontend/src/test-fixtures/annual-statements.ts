import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseAnnualStatements } from '@/types/agents/annual-statements';

export function loadAnnualStatementFixture() {
    const wire: unknown = JSON.parse(readFileSync(resolve(process.cwd(), '../contracts/fixtures/annual-statements.v1.json'), 'utf8'));
    return parseAnnualStatements(wire, 'annual statement contract fixture');
}
