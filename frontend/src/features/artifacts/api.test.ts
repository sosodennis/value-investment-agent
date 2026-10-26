import { describe, expect, it } from 'vitest';
import {
    buildArtifactUrl,
    resolveArtifactReferenceUrl,
} from './api';

describe('artifact API URLs', () => {
    it('encodes artifact IDs as one path segment', () => {
        expect(buildArtifactUrl('report /?1')).toBe(
            'http://localhost:8000/api/v1/artifacts/report%20%2F%3F1'
        );
    });

    it('keeps absolute HTTP references intact', () => {
        expect(
            resolveArtifactReferenceUrl('https://reports.example/report-1')
        ).toBe('https://reports.example/report-1');
    });
});
