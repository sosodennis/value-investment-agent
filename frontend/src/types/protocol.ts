export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    type?: 'text' | 'financial_report' | 'interrupt.request';
    data?: unknown;
    isInteractive?: boolean;
    created_at?: string | null;
    agentId?: string;
}

export const parseApiErrorMessage = (value: unknown): string | null => {
    if (typeof value !== 'object' || value === null || Array.isArray(value) || !('detail' in value)) return null;
    const detail = value.detail;
    if (typeof detail === 'string') return detail;
    if (!Array.isArray(detail)) return null;
    const messages = detail.flatMap((entry: unknown) => {
        if (typeof entry !== 'object' || entry === null || Array.isArray(entry) || !('msg' in entry) || typeof entry.msg !== 'string') return [];
        const location = 'loc' in entry && Array.isArray(entry.loc) && entry.loc.every((part: unknown) => typeof part === 'string' || typeof part === 'number') ? entry.loc.map(String).join('.') : '';
        return [location ? `${location}: ${entry.msg}` : entry.msg];
    });
    return messages.length ? messages.join('; ') : null;
};
