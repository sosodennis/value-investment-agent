import { describe, expect, it } from 'vitest';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { projectFundamentalReport } from './fundamental-report-model';
import { reference } from './fundamental-report.test-fixtures';
import { percentTextToRatio, ratioToPercentText, valuationRevisionAvailability } from './valuation-revision';
import { editableReport, forwardReview, revisionContext } from './valuation-revision.test-fixtures';
import { applyValuationClaim, createValuationRevisionState, validateValuationRevisionDraft, valuationRevisionReducer } from './valuation-revision-state';
import { buildFundamentalRevisionRequest } from '../../valuation-request';

describe('exact percentage editing', () => {
    it.each([
        ['8', '0.08'], ['0', '0'], ['-1', '-0.01'], ['.5', '0.005'], ['  +8.000 ', '0.08'],
        ['123456789012345678901234567890.123456789', '1234567890123456789012345678.90123456789'],
        ['1e400', '1e398'], ['1e-400', '1e-402'], ['8e2', '8'],
    ])('converts %s percent into exact ratio %s', (percentage, ratio) => {
        expect(percentTextToRatio(percentage)).toBe(ratio);
    });
    it.each([['0.08', '8'], ['-.0025', '-0.25'], ['.5', '50'], ['1e-2', '1'], ['1e400', '1e402'], ['0e400', '0']])('displays ratio %s as percentage %s', (ratio, percentage) => {
        expect(ratioToPercentText(ratio)).toBe(percentage);
    });
    it.each(['', '-', 'NaN', 'Infinity', '8%', '1,2', '1e', '1.2.3'])('rejects invalid percentage %s', (value) => {
        expect(() => percentTextToRatio(value)).toThrow(/finite decimal/);
    });
});

describe('source-bound revision draft', () => {
    it('sends only the generated revision intent without preparation or caller provenance', () => {
        const context = revisionContext();
        const state = createValuationRevisionState(context);
        const checked = validateValuationRevisionDraft(context, { ...state.draft, percentage: '8', reason: 'Updated evidence.' });
        if (checked.kind !== 'valid') throw new Error('Expected valid draft.');
        expect(buildFundamentalRevisionRequest(checked.revision)).toEqual({ contract_version: 'fundamental.v1', revision: {
            source: context.source, path: 'assumptions.terminal_growth', value: '0.08', reason: 'Updated evidence.',
        } });
    });
    it('requires a finite value and reason while preserving draft text', () => {
        const context = revisionContext();
        const state = createValuationRevisionState(context);
        expect(validateValuationRevisionDraft(context, { ...state.draft, percentage: '', reason: ' ' })).toEqual({ kind: 'invalid', errors: { value: 'Enter a finite decimal percentage.', reason: 'Explain why you are changing this assumption.' } });
        expect(state.draft.percentage).toBe('2');
    });
    it('stages a licensed accepted claim and removes its provenance after a manual value change', () => {
        const context = revisionContext();
        const review = forwardReview();
        const claim = review.claims[0];
        if (!claim) throw new Error('Expected claim fixture.');
        const applied = applyValuationClaim(context, review, claim);
        if (applied.kind !== 'applied') throw new Error('Expected applicable claim.');
        const staged = valuationRevisionReducer(createValuationRevisionState(context), { type: 'claim-applied', sourceKey: context.sourceKey, claimId: claim.claim_id, ...applied });
        expect(staged.draft).toMatchObject({ percentage: '3', forwardReference: { claim_id: 'claim-1', citation: claim.source.retained_passage, license_reference: 'issuer-terms-v1' } });
        const edited = valuationRevisionReducer(staged, { type: 'value-edited', sourceKey: context.sourceKey, percentage: '2.5' });
        expect(edited.draft.forwardReference).toBeNull();
        expect(edited.apply.kind).toBe('idle');
    });
    it.each(['digest', 'issuer', 'path', 'license'] as const)('refuses a claim with mismatched %s', (field) => {
        const review = forwardReview();
        const claim = review.claims[0];
        if (!claim) throw new Error('Expected claim fixture.');
        if (field === 'digest') review.automatic_preparation_digest = '0'.repeat(64);
        if (field === 'issuer') claim.issuer_id = 'other-issuer';
        if (field === 'path') claim.assumption_path = 'assumptions.wacc';
        if (field === 'license') claim.source.license_status = 'unknown';
        expect(applyValuationClaim(revisionContext(), review, claim).kind).toBe('error');
    });
    it('ignores late results from another source or superseded research operation', () => {
        const context = revisionContext();
        const state = valuationRevisionReducer(createValuationRevisionState(context), { type: 'research-started', sourceKey: context.sourceKey, operationId: 'new' });
        expect(valuationRevisionReducer(state, { type: 'research-ready', sourceKey: revisionContext('run-2').sourceKey, operationId: 'new', review: forwardReview() })).toBe(state);
        expect(valuationRevisionReducer(state, { type: 'research-ready', sourceKey: context.sourceKey, operationId: 'old', review: forwardReview() })).toBe(state);
    });
});

describe('revision availability', () => {
    function available(source = editableReport()) {
        return valuationRevisionAvailability(projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(source), reference, threadId: 'thread-1', ticker: 'WRONG' }));
    }
    it('uses service editability and parsed source security identity', () => {
        const result = available();
        expect(result).toMatchObject({ kind: 'available', context: { ticker: 'EXAMPLE', savedValue: '0.02', source: { thread_id: 'thread-1', run_id: 'run-1', artifact_id: 'report-1' } } });
    });
    it.each(['conditional_revision_ref', 'manual_flag', 'uneditable', 'duplicate'] as const)('keeps %s sources read-only', (condition) => {
        const source = editableReport();
        const automatic = source.automatic_preparation;
        if (!automatic) throw new Error('Expected preparation fixture.');
        const first = automatic.assumptions_evidence[0];
        if (!first) throw new Error('Expected assumption fixture.');
        if (condition === 'conditional_revision_ref') automatic.input = { ...automatic.input, provenance: { conditional_revision_ref: 'revision-source-1' } };
        if (condition === 'manual_flag') automatic.issue_codes.push('MANUAL_OVERRIDE_APPLIED');
        if (condition === 'uneditable') first.editable = false;
        if (condition === 'duplicate') automatic.assumptions_evidence.push({ ...first });
        expect(available(source).kind).toBe('read-only');
    });
});
