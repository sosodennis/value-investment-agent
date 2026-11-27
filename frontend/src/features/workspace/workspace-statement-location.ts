type StatementExpectation = { threadId: string; artifactId: string; editionIdentity: string };
export type SavedStatementExpectation =
    | { kind: 'absent' }
    | { kind: 'invalid' }
    | { kind: 'bound'; value: StatementExpectation };

const REFERENCE_EVENT = 'statement-reference';

function historyExpectation(): SavedStatementExpectation {
    const state: unknown = window.history.state;
    if (typeof state !== 'object' || state === null || !('statementReadExpectation' in state)) return { kind: 'absent' };
    const value = state.statementReadExpectation;
    if (typeof value !== 'object' || value === null
        || !('threadId' in value) || typeof value.threadId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.threadId)
        || !('artifactId' in value) || typeof value.artifactId !== 'string' || !/^[A-Za-z0-9-]{1,128}$/.test(value.artifactId)
        || !('editionIdentity' in value) || typeof value.editionIdentity !== 'string' || value.editionIdentity.length === 0) return { kind: 'invalid' };
    return { kind: 'bound', value: { threadId: value.threadId, artifactId: value.artifactId, editionIdentity: value.editionIdentity } };
}

function ownHistoryData() {
    const expectation = historyExpectation();
    return expectation.kind === 'absent' ? null : { statementReadExpectation: expectation.kind === 'bound' ? expectation.value : null };
}

export function savedStatementExpectation(threadId: string, artifactId: string): SavedStatementExpectation {
    const expectation = historyExpectation();
    if (expectation.kind === 'bound' && (expectation.value.threadId !== threadId || expectation.value.artifactId !== artifactId)) return { kind: 'invalid' };
    return expectation;
}

export function subscribeStatementLocation(callback: () => void) {
    window.addEventListener('popstate', callback);
    window.addEventListener(REFERENCE_EVENT, callback);
    return () => { window.removeEventListener('popstate', callback); window.removeEventListener(REFERENCE_EVENT, callback); };
}

export function statementLocationSnapshot() { return JSON.stringify([window.location.search, historyExpectation()]); }
export function statementServerLocationSnapshot() { return ''; }

export function saveStatementReference(expectation: StatementExpectation, frequency: 'annual' | 'quarter' | 'ttm') {
    const url = new URL(window.location.href);
    url.searchParams.set('statement_thread', expectation.threadId);
    url.searchParams.set('statement_artifact', expectation.artifactId);
    url.searchParams.set('statement_frequency', frequency);
    url.searchParams.delete('statement_period');
    window.history.pushState({ statementReadExpectation: expectation }, '', url);
    window.dispatchEvent(new Event(REFERENCE_EVENT));
}

export function saveStatementPeriod(period: string) {
    const url = new URL(window.location.href);
    if (period) url.searchParams.set('statement_period', period); else url.searchParams.delete('statement_period');
    if (url.href !== window.location.href) window.history.pushState(ownHistoryData(), '', url);
    window.dispatchEvent(new Event(REFERENCE_EVENT));
}

export function replaceStatementLocation(url: URL) {
    window.history.replaceState(ownHistoryData(), '', url);
    window.dispatchEvent(new Event(REFERENCE_EVENT));
}

export function retainStatementCreationId(): string {
    const url = new URL(window.location.href);
    const retained = url.searchParams.get('statement_creation');
    const id = retained && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(retained) ? retained : crypto.randomUUID();
    url.searchParams.set('statement_creation', id);
    replaceStatementLocation(url);
    return id;
}
