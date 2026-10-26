import type { ArtifactReference } from '@/types/agents';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export function buildArtifactUrl(artifactId: string, runId?: string): string {
    const base = `${API_URL}/api/v1/artifacts/${encodeURIComponent(artifactId)}`;
    return runId ? `${base}?run_id=${encodeURIComponent(runId)}` : base;
}

type ArtifactReferenceUrlInput = string | Pick<ArtifactReference, 'download_url'>;

export function buildArtifactReferenceUrl(
    reference: ArtifactReferenceUrlInput
): string {
    const value = typeof reference === 'string' ? reference : reference.download_url;
    if (value.startsWith('http://') || value.startsWith('https://')) return value;
    if (value.startsWith('/')) return value;
    return buildArtifactUrl(value);
}
