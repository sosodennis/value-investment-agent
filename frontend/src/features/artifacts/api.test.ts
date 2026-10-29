import { describe, expect, it } from 'vitest';
import {
    buildArtifactReferenceUrl,
    buildArtifactUrl,
    getArtifactRunId,
} from './api';

describe('artifact API URLs', () => {
    it('encodes artifact IDs as one path segment', () => {
        expect(buildArtifactUrl('report /?1')).toBe(
            '/api/v1/artifacts/report%20%2F%3F1'
        );
    });

    it('keeps absolute HTTP references intact', () => {
        expect(
            buildArtifactReferenceUrl('https://reports.example/report-1')
        ).toBe('https://reports.example/report-1');
        expect(
            buildArtifactReferenceUrl({
                download_url: 'https://reports.example/report-1',
            })
        ).toBe('https://reports.example/report-1');
    });

    it('keeps relative API references intact', () => {
        expect(
            buildArtifactReferenceUrl('/api/v1/artifacts/report-1?run_id=run-1')
        ).toBe('/api/v1/artifacts/report-1?run_id=run-1');
    });

    it('keeps legacy backend artifact references on the same origin', () => {
        expect(buildArtifactReferenceUrl('http://127.0.0.1:8000/api/v1/artifacts/report-1?run_id=run-2'))
            .toBe('/api/v1/artifacts/report-1?run_id=run-2');
    });

    it('reads the run scope from relative and absolute artifact references', () => {
        expect(getArtifactRunId({ download_url: '/api/v1/artifacts/report-1?run_id=run-1' })).toBe('run-1');
        expect(getArtifactRunId({ download_url: 'http://localhost:8000/api/v1/artifacts/report-1?run_id=run%2F2' })).toBe('run/2');
        expect(getArtifactRunId({ download_url: '/api/v1/artifacts/report-1' })).toBeNull();
    });
});
