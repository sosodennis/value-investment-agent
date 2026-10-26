const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export function buildArtifactUrl(artifactId: string, runId?: string): string {
    const base = `${API_URL}/api/v1/artifacts/${encodeURIComponent(artifactId)}`;
    return runId ? `${base}?run_id=${encodeURIComponent(runId)}` : base;
}

export function resolveArtifactReferenceUrl(reference: string): string {
    return reference.startsWith('https://') || reference.startsWith('http://')
        ? reference
        : buildArtifactUrl(reference);
}
