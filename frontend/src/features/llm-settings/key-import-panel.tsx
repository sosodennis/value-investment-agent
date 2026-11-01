'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Copy, Info, LoaderCircle, RefreshCw, X } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@/components/ui/popover';
import {
    createLlmProviderKeyImport,
    getLlmProviderKeyImport,
    listLlmProviderKeyImports,
    LlmSettingsApiError,
    previewLlmProviderKeyImport,
    retryLlmProviderKeyImport,
    type LlmProviderKeyImport,
    type LlmProviderKeyImportItemStatus,
    type LlmProviderKeyImportPreview,
} from '@/features/llm-settings/api';

const TXT_EXAMPLE = [
    'sk-or-v1-example-key-one-not-real-0000001',
    'sk-or-v1-example-key-two-not-real-0000002',
].join('\n');

const CSV_EXAMPLE = [
    'api_key,label',
    'sk-or-v1-example-key-one-not-real-0000001,Research primary',
    'sk-or-v1-example-key-two-not-real-0000002,Research backup',
].join('\n');

type KeyImportPanelProps = {
    authenticated: boolean;
    canMutate: boolean;
    onUnauthorized: (cause: unknown) => boolean;
    submittedImports: LlmProviderKeyImport[];
    onImportCompleted: () => void;
};

function mergeImports(
    current: LlmProviderKeyImport[],
    incoming: LlmProviderKeyImport[],
): LlmProviderKeyImport[] {
    const byId = new Map<string, LlmProviderKeyImport>();
    for (const batch of [...incoming, ...current]) {
        const previous = byId.get(batch.id);
        if (!previous || batch.updated_at > previous.updated_at) {
            byId.set(batch.id, batch);
        }
    }
    return [...byId.values()]
        .sort((left, right) => right.created_at.localeCompare(left.created_at))
        .slice(0, 10);
}

function isTerminalImport(batch: LlmProviderKeyImport): boolean {
    return batch.status === 'completed' || batch.status === 'completed_with_errors';
}

function errorMessage(cause: unknown): string {
    if (!(cause instanceof LlmSettingsApiError)) {
        return 'Could not process this key file.';
    }
    switch (cause.code ?? cause.message) {
        case 'unsupported_file_type': return 'Choose a .txt or .csv file.';
        case 'file_too_large':
        case 'request_too_large': return 'The file must be no larger than 1 MiB.';
        case 'invalid_encoding': return 'The file must use UTF-8 text encoding.';
        case 'missing_api_key_header': return 'The CSV must include an api_key header.';
        case 'invalid_csv_header': return 'The CSV may contain only api_key and optional label columns.';
        case 'too_many_rows': return 'The file can contain up to 500 key rows.';
        case 'invalid_rows': return 'Fix the file rows shown in the preview before importing.';
        case 'no_keys_found': return 'The file does not contain any keys.';
        case 'invalid_multipart':
        case 'multipart_required':
        case 'file_required': return 'Choose a valid text file to continue.';
        default: return cause.message;
    }
}

function parseIssueMessage(code: string): string {
    switch (code) {
        case 'invalid_key_format': return 'Key must be 20 to 500 characters with no spaces.';
        case 'invalid_csv_row': return 'Row must contain an api_key value.';
        case 'invalid_label': return 'Label must be at most 80 characters.';
        default: return 'Row is invalid.';
    }
}

function itemStatusText(status: LlmProviderKeyImportItemStatus): string {
    switch (status) {
        case 'queued': return 'Waiting';
        case 'validating': return 'Checking';
        case 'retry_wait': return 'Retrying';
        case 'imported': return 'Imported';
        case 'duplicate': return 'Duplicate';
        case 'invalid': return 'Invalid';
        case 'unavailable': return 'Unavailable';
        case 'expired': return 'Expired';
        default: {
            const exhaustive: never = status;
            return exhaustive;
        }
    }
}

function itemStatusVariant(
    status: LlmProviderKeyImportItemStatus,
): 'success' | 'warning' | 'destructive' | 'outline' {
    switch (status) {
        case 'imported': return 'success';
        case 'retry_wait':
        case 'validating': return 'warning';
        case 'invalid':
        case 'unavailable':
        case 'expired': return 'destructive';
        case 'queued':
        case 'duplicate': return 'outline';
        default: {
            const exhaustive: never = status;
            return exhaustive;
        }
    }
}

function batchStatusText(batch: LlmProviderKeyImport): string {
    switch (batch.status) {
        case 'queued': return 'Queued';
        case 'processing': return 'Processing';
        case 'completed': return 'Completed';
        case 'completed_with_errors': return 'Completed with errors';
        default: {
            const exhaustive: never = batch.status;
            return exhaustive;
        }
    }
}

export function KeyImportPanel({
    authenticated,
    canMutate,
    onUnauthorized,
    submittedImports,
    onImportCompleted,
}: KeyImportPanelProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const previewRequestRef = useRef(0);
    const pollingRef = useRef(false);
    const idempotencyKeyRef = useRef<string | null>(null);
    const completedBatchIdsRef = useRef(new Set<string>());
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [preview, setPreview] = useState<LlmProviderKeyImportPreview | null>(null);
    const [imports, setImports] = useState<LlmProviderKeyImport[]>([]);
    const [copiedExample, setCopiedExample] = useState<'txt' | 'csv' | null>(null);
    const [isPreviewing, setIsPreviewing] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isLoadingImports, setIsLoadingImports] = useState(true);
    const [retryingBatchId, setRetryingBatchId] = useState<string | null>(null);
    const [fileError, setFileError] = useState<string | null>(null);
    const [importError, setImportError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const notifyCompletedImport = useCallback((batch: LlmProviderKeyImport) => {
        if (
            !isTerminalImport(batch) ||
            batch.imported_count === 0 ||
            completedBatchIdsRef.current.has(batch.id)
        ) {
            return;
        }
        completedBatchIdsRef.current.add(batch.id);
        onImportCompleted();
    }, [onImportCompleted]);

    const trackImports = useCallback((batches: LlmProviderKeyImport[]) => {
        batches.forEach(notifyCompletedImport);
    }, [notifyCompletedImport]);

    const refreshImports = useCallback(async () => {
        setIsLoadingImports(true);
        try {
            const result = await listLlmProviderKeyImports();
            setImports((current) => mergeImports(current, result));
            trackImports(result);
            setImportError(null);
        } catch (cause) {
            if (!onUnauthorized(cause)) {
                setImportError('Could not load key import history.');
            }
        } finally {
            setIsLoadingImports(false);
        }
    }, [onUnauthorized, trackImports]);

    useEffect(() => {
        if (!authenticated) return;
        let cancelled = false;
        void listLlmProviderKeyImports().then((result) => {
            if (cancelled) return;
            setImports((current) => mergeImports(current, result));
            trackImports(result);
            setImportError(null);
        }).catch((cause: unknown) => {
            if (cancelled || onUnauthorized(cause)) return;
            setImportError('Could not load key import history.');
        }).finally(() => {
            if (!cancelled) setIsLoadingImports(false);
        });
        return () => {
            cancelled = true;
        };
    }, [authenticated, onUnauthorized, trackImports]);

    useEffect(() => {
        trackImports(submittedImports);
    }, [submittedImports, trackImports]);

    const visibleImports = mergeImports(
        submittedImports,
        imports,
    );

    const activeBatchIds = visibleImports
        .filter((batch) => batch.status === 'queued' || batch.status === 'processing')
        .map((batch) => batch.id);
    const activeBatchKey = activeBatchIds.join(',');

    useEffect(() => {
        if (!authenticated || !activeBatchKey) return;
        const batchIds = activeBatchKey.split(',');
        const timer = window.setInterval(() => {
            if (pollingRef.current) return;
            pollingRef.current = true;
            void Promise.all(batchIds.map((batchId) =>
                getLlmProviderKeyImport(batchId)
            )).then((updated) => {
                updated.forEach(notifyCompletedImport);
                setImports((current) => mergeImports(current, updated));
            }).catch((cause: unknown) => {
                if (onUnauthorized(cause)) return;
                setImportError('Could not refresh key import progress.');
            }).finally(() => {
                pollingRef.current = false;
            });
        }, 1500);
        return () => window.clearInterval(timer);
    }, [activeBatchKey, authenticated, notifyCompletedImport, onUnauthorized]);

    async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
        const file = event.currentTarget.files?.[0] ?? null;
        const requestId = previewRequestRef.current + 1;
        previewRequestRef.current = requestId;
        setSelectedFile(file);
        setPreview(null);
        setFileError(null);
        setNotice(null);
        idempotencyKeyRef.current = file ? crypto.randomUUID() : null;
        if (!file) return;

        setIsPreviewing(true);
        try {
            const result = await previewLlmProviderKeyImport(file);
            if (previewRequestRef.current === requestId) setPreview(result);
        } catch (cause) {
            if (previewRequestRef.current !== requestId) return;
            if (!onUnauthorized(cause)) setFileError(errorMessage(cause));
        } finally {
            if (previewRequestRef.current === requestId) setIsPreviewing(false);
        }
    }

    function clearSelectedFile() {
        previewRequestRef.current += 1;
        setSelectedFile(null);
        setPreview(null);
        setFileError(null);
        idempotencyKeyRef.current = null;
        if (fileInputRef.current) fileInputRef.current.value = '';
    }

    async function handleImport() {
        const file = selectedFile;
        if (!file || !preview || preview.issues.length > 0 || preview.unique_count === 0) return;
        setIsSubmitting(true);
        setFileError(null);
        setNotice(null);
        const idempotencyKey = idempotencyKeyRef.current ?? crypto.randomUUID();
        idempotencyKeyRef.current = idempotencyKey;
        try {
            const batch = await createLlmProviderKeyImport(file, idempotencyKey);
            setImports((current) => mergeImports(current, [batch]));
            trackImports([batch]);
            clearSelectedFile();
            setNotice('The import was accepted. Its results will remain available here.');
        } catch (cause) {
            if (!onUnauthorized(cause)) setFileError(errorMessage(cause));
        } finally {
            setIsSubmitting(false);
        }
    }

    async function handleRetry(batchId: string) {
        setRetryingBatchId(batchId);
        setImportError(null);
        try {
            const updated = await retryLlmProviderKeyImport(batchId);
            completedBatchIdsRef.current.delete(updated.id);
            notifyCompletedImport(updated);
            setImports((current) => mergeImports(current, [updated]));
        } catch (cause) {
            if (!onUnauthorized(cause)) setImportError(errorMessage(cause));
        } finally {
            setRetryingBatchId(null);
        }
    }

    async function copyExample(format: 'txt' | 'csv') {
        try {
            await navigator.clipboard.writeText(format === 'txt' ? TXT_EXAMPLE : CSV_EXAMPLE);
            setCopiedExample(format);
            window.setTimeout(() => setCopiedExample(null), 1500);
        } catch {
            setFileError('Clipboard access is unavailable in this browser.');
        }
    }

    const canSubmit =
        authenticated &&
        canMutate &&
        selectedFile !== null &&
        preview !== null &&
        preview.issues.length === 0 &&
        preview.unique_count > 0 &&
        !isSubmitting &&
        !isPreviewing;

    return (
        <section className="min-w-0 border-t border-border py-6" aria-labelledby="key-import-heading">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h2 id="key-import-heading" className="font-semibold">Import provider keys</h2>
                    <p className="mt-1 text-sm text-muted-foreground">Upload up to 500 OpenRouter keys from a text file.</p>
                    {!canMutate ? <p className="mt-2 text-sm text-warning">Only organization owners and admins can change provider keys.</p> : null}
                </div>
                <Popover>
                    <PopoverTrigger asChild>
                        <Button type="button" variant="ghost" size="icon" aria-label="File format information" title="File format information">
                            <Info aria-hidden="true" />
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="max-h-[min(70vh,34rem)] w-[calc(100vw-2rem)] overflow-y-auto sm:w-[28rem]">
                        <div className="grid gap-5">
                            <div>
                                <h3 className="font-semibold">TXT format</h3>
                                <p className="mt-1 text-sm text-muted-foreground">UTF-8, one key per non-empty line.</p>
                                <pre className="mt-2 overflow-x-auto rounded-sm border border-border bg-muted p-3 font-mono text-xs">{TXT_EXAMPLE}</pre>
                                <Button type="button" variant="outline" size="sm" className="mt-2" onClick={() => void copyExample('txt')}>
                                    {copiedExample === 'txt' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                                    {copiedExample === 'txt' ? 'Copied TXT example' : 'Copy TXT example'}
                                </Button>
                            </div>
                            <div>
                                <h3 className="font-semibold">CSV format</h3>
                                <p className="mt-1 text-sm text-muted-foreground">The header must be api_key. label is optional.</p>
                                <pre className="mt-2 overflow-x-auto rounded-sm border border-border bg-muted p-3 font-mono text-xs">{CSV_EXAMPLE}</pre>
                                <Button type="button" variant="outline" size="sm" className="mt-2" onClick={() => void copyExample('csv')}>
                                    {copiedExample === 'csv' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                                    {copiedExample === 'csv' ? 'Copied CSV example' : 'Copy CSV example'}
                                </Button>
                            </div>
                            <p className="text-xs text-muted-foreground">Maximum file size: 1 MiB. Maximum rows: 500. PDF, XLSX and DOCX files are not supported.</p>
                        </div>
                    </PopoverContent>
                </Popover>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                <Field label="Key file" htmlFor="key-import-file">
                    <input
                        ref={fileInputRef}
                        id="key-import-file"
                        type="file"
                        accept=".txt,.csv,text/plain,text/csv"
                        disabled={!authenticated || !canMutate || isPreviewing || isSubmitting}
                        onChange={(event) => void handleFileChange(event)}
                        className="block min-h-10 w-full cursor-pointer rounded-sm border border-input bg-background text-sm text-foreground file:mr-3 file:min-h-10 file:border-0 file:border-r file:border-input file:bg-muted file:px-3 file:text-sm file:font-medium file:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                    />
                </Field>
                <div className="flex gap-2">
                    {selectedFile ? (
                        <Button type="button" variant="ghost" size="icon" aria-label="Clear selected file" title="Clear selected file" onClick={clearSelectedFile} disabled={isPreviewing || isSubmitting}>
                            <X aria-hidden="true" />
                        </Button>
                    ) : null}
                    <Button type="button" onClick={() => void handleImport()} disabled={!canSubmit}>
                        {isSubmitting ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}
                        {isSubmitting ? 'Submitting…' : 'Import keys'}
                    </Button>
                </div>
            </div>

            {isPreviewing ? <p className="mt-3 inline-flex items-center gap-2 text-sm text-muted-foreground" role="status"><LoaderCircle className="size-4 animate-spin" />Checking file</p> : null}
            {preview ? (
                <div className="mt-3 grid gap-2" aria-live="polite">
                    <p className="text-sm text-foreground">
                        {preview.row_count} rows · {preview.unique_count} unique keys · {preview.duplicate_count} duplicate rows
                    </p>
                    {preview.issues.length > 0 ? (
                        <ul className="grid gap-1 text-sm text-destructive">
                            {preview.issues.map((issue) => (
                                <li key={`${issue.source_line}-${issue.code}`}>
                                    Line {issue.source_line}: {parseIssueMessage(issue.code)}
                                </li>
                            ))}
                        </ul>
                    ) : null}
                </div>
            ) : null}
            {fileError ? <Alert variant="destructive" role="alert" className="mt-3"><AlertDescription>{fileError}</AlertDescription></Alert> : null}
            {notice ? <Alert variant="success" role="status" className="mt-3"><AlertDescription>{notice}</AlertDescription></Alert> : null}

            <div className="mt-6 border-t border-border pt-5">
                <div className="flex items-center justify-between gap-3">
                    <h3 className="font-medium">Import history</h3>
                    <Button type="button" variant="ghost" size="icon" onClick={() => void refreshImports()} disabled={!authenticated || isLoadingImports} aria-label="Refresh import history" title="Refresh import history">
                        {isLoadingImports ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
                    </Button>
                </div>
                {importError ? <Alert variant="destructive" role="alert" className="mt-3"><AlertDescription className="flex flex-wrap items-center justify-between gap-3"><span>{importError}</span><Button type="button" variant="outline" size="sm" onClick={() => void refreshImports()}>Retry history</Button></AlertDescription></Alert> : null}
                {isLoadingImports ? <p className="py-4 text-sm text-muted-foreground" role="status">Loading import history</p> : null}
                {!isLoadingImports && visibleImports.length === 0 ? <p className="py-4 text-sm text-muted-foreground">No key imports yet.</p> : null}
                <div className="mt-3 grid gap-3">
                    {visibleImports.map((batch) => {
                        const progress = batch.total_count === 0
                            ? 100
                            : Math.round((batch.processed_count / batch.total_count) * 100);
                        const canRetry = batch.retryable_count > 0 &&
                            batch.status !== 'queued' && batch.status !== 'processing';
                        return (
                            <article key={batch.id} className="min-w-0 rounded-sm border border-border p-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="flex items-center gap-2">
                                        <Badge variant={batch.status === 'completed' ? 'success' : batch.status === 'completed_with_errors' ? 'warning' : 'outline'}>
                                            {batchStatusText(batch)}
                                        </Badge>
                                        <span className="text-sm font-medium">{batch.processed_count} / {batch.total_count}</span>
                                    </div>
                                    {canRetry ? (
                                        <Button type="button" variant="outline" size="sm" onClick={() => void handleRetry(batch.id)} disabled={!canMutate || retryingBatchId !== null}>
                                            {retryingBatchId === batch.id ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
                                            {retryingBatchId === batch.id ? 'Retrying' : `Retry ${batch.retryable_count}`}
                                        </Button>
                                    ) : null}
                                </div>
                                <div className="mt-2 h-1.5 overflow-hidden rounded-sm bg-muted" role="progressbar" aria-label="Key import progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
                                    <div className="h-full bg-primary transition-[width]" style={{ width: `${progress}%` }} />
                                </div>
                                <p className="mt-2 text-xs text-muted-foreground">
                                    {batch.imported_count} imported · {batch.duplicate_count} duplicates · {batch.invalid_count} failed
                                    {batch.retryable_count > 0 ? ` · ${batch.retryable_count} retryable` : ''}
                                </p>
                                {(batch.items ?? []).length > 0 ? (
                                    <details className="mt-3">
                                        <summary className="cursor-pointer text-sm text-primary">View per-key results</summary>
                                        <div className="mt-2 max-h-64 overflow-auto rounded-sm border border-border">
                                            <table className="w-full text-left text-xs">
                                                <thead className="sticky top-0 bg-muted text-muted-foreground">
                                                    <tr><th className="px-3 py-2 font-medium">Line</th><th className="px-3 py-2 font-medium">Label</th><th className="px-3 py-2 font-medium">Result</th><th className="px-3 py-2 font-medium">Attempts</th></tr>
                                                </thead>
                                                <tbody>
                                                    {(batch.items ?? []).map((item) => (
                                                        <tr key={`${item.source_line}-${item.label}`} className="border-t border-border">
                                                            <td className="px-3 py-2 tabular-nums">{item.source_line}</td>
                                                            <td className="max-w-48 truncate px-3 py-2">{item.label}</td>
                                                            <td className="px-3 py-2"><Badge variant={itemStatusVariant(item.status)}>{itemStatusText(item.status)}</Badge></td>
                                                            <td className="px-3 py-2 tabular-nums">{item.attempts}</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    </details>
                                ) : null}
                            </article>
                        );
                    })}
                </div>
            </div>
        </section>
    );
}
