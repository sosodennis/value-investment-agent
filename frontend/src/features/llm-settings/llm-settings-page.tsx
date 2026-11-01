'use client';

import type { FormEvent } from 'react';
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { AlertCircle, Check, KeyRound, LoaderCircle, Plus, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';

import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Combobox } from '@/components/ui/combobox';
import { EmptyState } from '@/components/ui/empty-state';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { KeyImportPanel } from '@/features/llm-settings/key-import-panel';
import { useOrganizationContext } from '@/features/organizations/organization-context';
import {
    deleteLlmProviderKey,
    getLlmSettings,
    listLlmProviderKeys,
    LlmSettingsApiError,
    replaceLlmProviderKey,
    type LlmProviderKey,
    type LlmProviderKeyImport,
    type LlmModelOption,
    submitLlmProviderKey,
    testLlmProviderKey,
    updateLlmSettings,
} from '@/features/llm-settings/api';

type KeyOperation = { kind: 'test' | 'delete'; id: string } | null;
const LABEL_DRAFT_STORAGE_KEY = 'llm-settings-label-draft';
const LABEL_DRAFT_EVENT = 'llm-settings-label-draft-change';

function subscribeLabelDraft(onStoreChange: () => void): () => void {
    if (typeof window === 'undefined') return () => {};
    window.addEventListener('storage', onStoreChange);
    window.addEventListener(LABEL_DRAFT_EVENT, onStoreChange);
    return () => {
        window.removeEventListener('storage', onStoreChange);
        window.removeEventListener(LABEL_DRAFT_EVENT, onStoreChange);
    };
}

function getLabelDraftSnapshot(): string | null {
    if (typeof window === 'undefined') return null;
    return window.sessionStorage.getItem(LABEL_DRAFT_STORAGE_KEY);
}

function setStoredLabelDraft(value: string | null): void {
    if (typeof window === 'undefined') return;
    if (value) window.sessionStorage.setItem(LABEL_DRAFT_STORAGE_KEY, value);
    else window.sessionStorage.removeItem(LABEL_DRAFT_STORAGE_KEY);
    window.dispatchEvent(new Event(LABEL_DRAFT_EVENT));
}

const getServerLabelDraftSnapshot = (): null => null;

function formatDate(value: string | null | undefined, withTime = false): string {
    if (!value) return withTime ? 'Never' : 'Unknown date';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Unknown date';
    return new Intl.DateTimeFormat(undefined, withTime
        ? { dateStyle: 'medium', timeStyle: 'short' }
        : { dateStyle: 'medium' }).format(date);
}

function keyStatusLabel(status: string | undefined, cooldownUntil: string | null | undefined): string {
    switch (status) {
        case 'healthy': return 'Healthy';
        case 'invalid_key': return 'Invalid key';
        case 'unavailable': return 'Unavailable';
        case 'available': return 'Available';
        case 'replacement_grace': return 'Replacing';
        case 'cooldown': return cooldownUntil ? 'Cooling down' : 'Available';
        default: return 'Not tested';
    }
}

function keyErrorLabel(code: string | null | undefined): string | null {
    switch (code) {
        case 'invalid_key': return 'The provider rejected this key.';
        case 'rate_limited': return 'The provider rate limited this key.';
        case 'global_rate_limited': return 'The provider is rate limiting requests.';
        case 'credit_limit': return 'The provider credit limit blocked this request.';
        case 'upstream_timeout': return 'The provider request timed out.';
        case 'unavailable': return 'The provider request failed.';
        default: return null;
    }
}

function isIdempotencyKeyConflict(cause: unknown): boolean {
    return cause instanceof LlmSettingsApiError &&
        (cause.code === 'idempotency_key_reused' || cause.message === 'idempotency_key_reused');
}

function errorMessage(cause: unknown, fallback: string): string {
    if (!(cause instanceof LlmSettingsApiError)) return fallback;
    if (isIdempotencyKeyConflict(cause)) {
        return 'This request was already used for different content. Submit the key again.';
    }
    switch (cause.message) {
        case 'invalid_key': return 'OpenRouter rejected this API key.';
        case 'rate_limited': return 'OpenRouter is rate limiting requests. Try again shortly.';
        case 'unavailable': return 'The gateway or OpenRouter is currently unavailable.';
        case 'permission_denied': return 'You can view this organization provider configuration, but only an owner or admin can change it.';
        case 'organization_context_required': return 'Select an active organization to view provider configuration.';
        case 'resource_not_found': return 'The active organization provider configuration was not found.';
        default: return cause.message;
    }
}

function statusVariant(status: string | undefined): 'success' | 'warning' | 'destructive' | 'outline' {
    switch (status) {
        case 'healthy': return 'success';
        case 'cooldown':
        case 'replacement_grace': return 'warning';
        case 'invalid_key':
        case 'unavailable': return 'destructive';
        default: return 'outline';
    }
}

export default function LlmSettingsPage() {
    const router = useRouter();
    const { activeOrganization, isLoading: isLoadingOrganizations } = useOrganizationContext();
    const activeOrganizationId = activeOrganization?.id ?? null;
    const canMutate = activeOrganization?.role === 'owner' || activeOrganization?.role === 'admin';
    const organizationReady = !isLoadingOrganizations && activeOrganizationId !== null;
    const labelDraftRef = useRef('');
    const manualSubmissionKeyRef = useRef<string | null>(null);
    const redirectingRef = useRef(false);
    const storedLabelDraft = useSyncExternalStore(
        subscribeLabelDraft,
        getLabelDraftSnapshot,
        getServerLabelDraftSnapshot,
    );
    const [authenticated, setAuthenticated] = useState(false);
    const [keys, setKeys] = useState<LlmProviderKey[]>([]);
    const [keysOrganizationId, setKeysOrganizationId] = useState<string | null>(null);
    const [models, setModels] = useState<LlmModelOption[]>([]);
    const [modelsOrganizationId, setModelsOrganizationId] = useState<string | null>(null);
    const [selectedModel, setSelectedModel] = useState('openrouter/free');
    const [labelOverride, setLabelOverride] = useState<string | null>(null);
    const label = labelOverride ?? storedLabelDraft ?? '';
    const [apiKey, setApiKey] = useState('');
    const [apiKeyOrganizationId, setApiKeyOrganizationId] = useState<string | null>(null);
    const [submittedImports, setSubmittedImports] = useState<LlmProviderKeyImport[]>([]);
    const [submittedImportsOrganizationId, setSubmittedImportsOrganizationId] = useState<string | null>(null);
    const [keyLoadError, setKeyLoadError] = useState<string | null>(null);
    const [catalogError, setCatalogError] = useState<string | null>(null);
    const [operationError, setOperationError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [isLoadingKeysRequest, setIsLoadingKeysRequest] = useState(true);
    const [isRefreshingKeys, setIsRefreshingKeys] = useState(false);
    const [isLoadingModelsRequest, setIsLoadingModelsRequest] = useState(true);
    const [isAddingKey, setIsAddingKey] = useState(false);
    const [isSavingModel, setIsSavingModel] = useState(false);
    const [keyOperation, setKeyOperation] = useState<KeyOperation>(null);
    const [deleteCandidate, setDeleteCandidate] = useState<LlmProviderKey | null>(null);
    const [replacementCandidate, setReplacementCandidate] = useState<LlmProviderKey | null>(null);
    const hasCurrentKeys = organizationReady && keysOrganizationId === activeOrganizationId;
    const hasCurrentModels = organizationReady && modelsOrganizationId === activeOrganizationId;
    const visibleKeys = hasCurrentKeys ? keys : [];
    const visibleModels = hasCurrentModels ? models : [];
    const currentSelectedModel = hasCurrentModels ? selectedModel : 'openrouter/free';
    const visibleSubmittedImports = submittedImportsOrganizationId === activeOrganizationId
        ? submittedImports
        : [];
    const visibleApiKey = apiKeyOrganizationId === activeOrganizationId ? apiKey : '';
    const isLoadingKeys = organizationReady && (!hasCurrentKeys || isLoadingKeysRequest);
    const isLoadingModels = organizationReady && (!hasCurrentModels || isLoadingModelsRequest);

    const redirectToLogin = useCallback((cause: unknown): boolean => {
        if (!(cause instanceof LlmSettingsApiError) || cause.status !== 401) return false;
        if (redirectingRef.current) return true;
        const draft = (labelDraftRef.current || getLabelDraftSnapshot() || '').trim();
        setStoredLabelDraft(draft || null);
        redirectingRef.current = true;
        router.replace(`/login?next=${encodeURIComponent('/settings/llm')}`);
        return true;
    }, [router]);

    const loadKeys = useCallback(async (refresh = false) => {
        const organizationId = activeOrganizationId;
        if (!organizationReady || !organizationId) return;
        if (refresh) setIsRefreshingKeys(true);
        else setIsLoadingKeysRequest(true);
        setKeyLoadError(null);
        try {
            setKeys(await listLlmProviderKeys());
            setKeysOrganizationId(organizationId);
            setAuthenticated(true);
        } catch (cause) {
            setKeysOrganizationId(organizationId);
            if (!redirectToLogin(cause)) setKeyLoadError(errorMessage(cause, 'Could not load provider keys.'));
        } finally {
            setIsLoadingKeysRequest(false);
            setIsRefreshingKeys(false);
        }
    }, [activeOrganizationId, organizationReady, redirectToLogin]);

    const refreshKeysAfterImport = useCallback(() => {
        void loadKeys(true);
    }, [loadKeys]);

    const loadModels = useCallback(async () => {
        const organizationId = activeOrganizationId;
        if (!organizationReady || !organizationId) return;
        setIsLoadingModelsRequest(true);
        setCatalogError(null);
        try {
            const settings = await getLlmSettings();
            setAuthenticated(true);
            setModels(settings.models);
            setSelectedModel(settings.selected_model);
            setModelsOrganizationId(organizationId);
        } catch (cause) {
            setModelsOrganizationId(organizationId);
            if (!redirectToLogin(cause)) setCatalogError(errorMessage(cause, 'Could not load the model catalogue.'));
        } finally {
            setIsLoadingModelsRequest(false);
        }
    }, [activeOrganizationId, organizationReady, redirectToLogin]);

    useEffect(() => {
        if (!organizationReady || !activeOrganizationId) return;
        let active = true;
        void Promise.resolve().then(() => {
            if (!active) return;
            setKeyLoadError(null);
            setCatalogError(null);
            const keyRequest = listLlmProviderKeys()
                .then((nextKeys) => {
                if (!active) return;
                setKeys(nextKeys);
                setAuthenticated(true);
                })
                .catch((cause: unknown) => {
                if (!active) return;
                if (!redirectToLogin(cause)) setKeyLoadError(errorMessage(cause, 'Could not load provider keys.'));
                });
            const modelRequest = getLlmSettings()
                .then((settings) => {
                if (!active) return;
                setAuthenticated(true);
                setModels(settings.models);
                setSelectedModel(settings.selected_model);
                })
                .catch((cause: unknown) => {
                if (!active) return;
                if (!redirectToLogin(cause)) setCatalogError(errorMessage(cause, 'Could not load the model catalogue.'));
            });
            void Promise.all([keyRequest, modelRequest]).finally(() => {
                if (!active) return;
                setKeysOrganizationId(activeOrganizationId);
                setModelsOrganizationId(activeOrganizationId);
                setIsLoadingKeysRequest(false);
                setIsLoadingModelsRequest(false);
            });
        });
        return () => {
            active = false;
        };
    }, [activeOrganizationId, organizationReady, redirectToLogin]);

    async function handleModelChange(model: string) {
        if (!canMutate || !model || model === selectedModel) return;
        const previousModel = selectedModel;
        setSelectedModel(model);
        setIsSavingModel(true);
        setOperationError(null);
        setNotice(null);
        try {
            const settings = await updateLlmSettings(model);
            setModels(settings.models);
            setSelectedModel(settings.selected_model);
            setNotice(`Default model changed to ${settings.selected_model}.`);
        } catch (cause) {
            setSelectedModel(previousModel);
            if (!redirectToLogin(cause)) setOperationError(errorMessage(cause, 'Could not update the default model.'));
        } finally {
            setIsSavingModel(false);
        }
    }

    async function handleAddKey(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (isAddingKey || !visibleApiKey || !canMutate) return;
        const replacing = replacementCandidate !== null;
        setIsAddingKey(true);
        setOperationError(null);
        setNotice(null);
        try {
            const input = { label: label.trim() || 'OpenRouter key', api_key: visibleApiKey };
            if (replacing) {
                const created = await replaceLlmProviderKey(replacementCandidate.id, input);
                setKeys((current) => current.map((key) =>
                    key.id === replacementCandidate.id ? created : key
                ));
                setNotice(
                    `Key ending in ${created.suffix} passed its test and replaced ${input.label}.`,
                );
            } else {
                const idempotencyKey = manualSubmissionKeyRef.current ?? crypto.randomUUID();
                manualSubmissionKeyRef.current = idempotencyKey;
                const submitted = await submitLlmProviderKey(input, idempotencyKey);
                setSubmittedImports((current) => [
                    submitted,
                    ...current.filter((item) => item.id !== submitted.id),
                ].slice(0, 10));
                setSubmittedImportsOrganizationId(activeOrganizationId);
                manualSubmissionKeyRef.current = null;
                setNotice('The key was submitted. Track its status in import history.');
            }
            setReplacementCandidate(null);
            setLabelOverride('');
            labelDraftRef.current = '';
            setStoredLabelDraft(null);
                setApiKey('');
                setApiKeyOrganizationId(activeOrganizationId);
        } catch (cause) {
            if (isIdempotencyKeyConflict(cause)) {
                manualSubmissionKeyRef.current = null;
            }
            if (!redirectToLogin(cause)) setOperationError(errorMessage(cause, replacing ? 'Could not replace this key.' : 'Could not add this key.'));
        } finally {
            setIsAddingKey(false);
        }
    }

    async function handleTestKey(item: LlmProviderKey) {
        if (!canMutate) return;
        setKeyOperation({ kind: 'test', id: item.id });
        setOperationError(null);
        setNotice(null);
        try {
            const result = await testLlmProviderKey(item.id);
            setNotice(result.passed ? `${item.label} is healthy.` : `${item.label} did not pass its connection test.`);
        } catch (cause) {
            if (!redirectToLogin(cause)) setOperationError(errorMessage(cause, 'Could not test this key.'));
        } finally {
            setKeyOperation(null);
        }
    }

    async function confirmDelete() {
        if (!canMutate) return;
        const item = deleteCandidate;
        if (!item) return;
        setDeleteCandidate(null);
        setKeyOperation({ kind: 'delete', id: item.id });
        setOperationError(null);
        setNotice(null);
        try {
            await deleteLlmProviderKey(item.id);
            setKeys((current) => current.filter((key) => key.id !== item.id));
            setNotice(`${item.label} was deleted.`);
        } catch (cause) {
            if (!redirectToLogin(cause)) setOperationError(errorMessage(cause, 'Could not delete this key.'));
        } finally {
            setKeyOperation(null);
        }
    }

    const modelOptions = visibleModels.map((model) => ({
        value: model.id,
        label: model.name,
        keywords: [model.id, model.description ?? ''],
    }));

    return (
        <main className="min-h-[calc(100vh-4rem)] bg-background px-4 py-7 sm:px-8 sm:py-9 lg:px-10">
            <div className="mx-auto max-w-5xl">
                <header className="flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <p className="text-sm font-medium text-primary">LLM settings</p>
                        <h1 className="mt-2 font-headline text-2xl font-semibold">Provider configuration</h1>
                        <p className="mt-2 text-sm text-muted-foreground">Active organization: <span className="font-medium text-foreground">{activeOrganization?.name ?? 'None selected'}</span>{activeOrganization ? ` · ${activeOrganization.role}` : ''}</p>
                    </div>
                    <p className="inline-flex items-center gap-2 text-sm text-muted-foreground"><ShieldCheck aria-hidden="true" className="size-4 text-success" />Managed gateway</p>
                </header>

                <section className="border-b border-border py-6" aria-labelledby="model-heading">
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                            <h2 id="model-heading" className="font-semibold">Default OpenRouter model</h2>
                            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Choose the free model route used by analysis requests.</p>
                        </div>
                        {isSavingModel ? <span className="inline-flex items-center gap-2 text-sm text-muted-foreground" role="status"><LoaderCircle className="size-4 animate-spin" />Saving model</span> : null}
                    </div>
                    <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(16rem,28rem)_auto] sm:items-center">
                        <Combobox
                            ariaLabel="Default OpenRouter model"
                            value={currentSelectedModel}
                            options={modelOptions}
                            disabled={!authenticated || !canMutate || isLoadingModels || isSavingModel || modelOptions.length === 0}
                            placeholder={isLoadingModels ? 'Loading model catalogue...' : 'Select a model'}
                            searchPlaceholder="Search models..."
                            emptyMessage="No matching models."
                            onValueChange={(model) => void handleModelChange(model)}
                        />
                        <p className="break-all font-mono text-xs text-muted-foreground" aria-label="Selected model id">{currentSelectedModel}</p>
                    </div>
                    {isLoadingModels ? <p className="mt-3 text-sm text-muted-foreground" role="status">Loading model catalogue...</p> : null}
                    {catalogError ? <Alert variant="destructive" role="alert" className="mt-3"><AlertDescription className="flex flex-wrap items-center justify-between gap-3"><span>{catalogError}</span><Button variant="outline" size="sm" onClick={() => void loadModels()}>Retry catalogue</Button></AlertDescription></Alert> : null}
                    {!organizationReady ? <p className="mt-3 text-sm text-muted-foreground">Select an active organization to manage provider settings.</p> : null}
                    {organizationReady && !isLoadingModels && !catalogError && visibleModels.length === 0 ? <EmptyState className="min-h-24 items-start text-left" title="No free models available" description="The provider catalogue returned no free models." /> : null}
                </section>

                <div className="grid gap-7 lg:grid-cols-[minmax(16rem,0.7fr)_minmax(0,1.3fr)]">
                    <div className="min-w-0 border-b border-border lg:border-b-0 lg:border-r lg:pr-7">
                        <form onSubmit={(event) => void handleAddKey(event)} className="grid content-start gap-5 py-6" aria-labelledby="add-key-heading">
                            <div>
                                <h2 id="add-key-heading" className="font-semibold">{replacementCandidate ? `Replace ${replacementCandidate.label}` : 'Add a provider key'}</h2>
                                <p className="mt-1 text-sm text-muted-foreground">{replacementCandidate ? 'The replacement key is tested before it is saved.' : 'Submitted keys are checked in the background. Track the result in import history.'}</p>
                            </div>
                            {replacementCandidate ? <Button type="button" variant="ghost" className="justify-self-start" disabled={isAddingKey} onClick={() => { setReplacementCandidate(null); setLabelOverride(''); labelDraftRef.current = ''; setApiKey(''); }}>Cancel replacement</Button> : null}
                            <Field label="Label" htmlFor="key-label" description="Optional. Use a name you recognize.">
                                <Input id="key-label" value={label} onFocus={() => {
                                    if (labelOverride === null && storedLabelDraft !== null) {
                                        labelDraftRef.current = storedLabelDraft;
                                        setLabelOverride(storedLabelDraft);
                                        setStoredLabelDraft(null);
                                    }
                                }} onChange={(event) => {
                                    const nextLabel = event.target.value;
                                    if (nextLabel !== label) manualSubmissionKeyRef.current = null;
                                    labelDraftRef.current = nextLabel;
                                    setLabelOverride(nextLabel);
                                    if (storedLabelDraft !== null) setStoredLabelDraft(null);
                                }} placeholder="Primary research key" maxLength={80} disabled={isAddingKey || !canMutate} />
                            </Field>
                            <Field label="OpenRouter API key" htmlFor="openrouter-key">
                                <Input id="openrouter-key" type="password" value={visibleApiKey} onChange={(event) => {
                                    const nextKey = event.target.value;
                                    if (nextKey !== visibleApiKey) manualSubmissionKeyRef.current = null;
                                    setApiKey(nextKey);
                                    setApiKeyOrganizationId(activeOrganizationId);
                                }} placeholder="sk-or-v1-..." minLength={20} maxLength={500} autoComplete="off" required disabled={isAddingKey || !canMutate} />
                            </Field>
                            <Button type="submit" disabled={isAddingKey || !authenticated || !canMutate || !visibleApiKey}>
                                {isAddingKey ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : replacementCandidate ? <RefreshCw aria-hidden="true" /> : <Plus aria-hidden="true" />}
                                {isAddingKey ? (replacementCandidate ? 'Testing and replacing...' : 'Submitting key...') : replacementCandidate ? 'Test and replace key' : 'Add key'}
                            </Button>
                        </form>
                        <KeyImportPanel
                            key={activeOrganizationId ?? 'no-organization'}
                            authenticated={authenticated && organizationReady}
                            canMutate={canMutate}
                            onUnauthorized={redirectToLogin}
                            submittedImports={visibleSubmittedImports}
                            onImportCompleted={refreshKeysAfterImport}
                        />
                    </div>

                    <section className="min-w-0 py-6" aria-labelledby="keys-heading">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <h2 id="keys-heading" className="font-semibold">Configured keys</h2>
                                <p className="mt-1 text-sm text-muted-foreground">Only masked identifiers are shown.</p>
                            </div>
                            <Button variant="ghost" size="icon" onClick={() => void loadKeys(true)} disabled={isLoadingKeys || isRefreshingKeys || !authenticated} aria-label="Refresh keys" title="Refresh keys">
                                {isRefreshingKeys ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
                            </Button>
                        </div>
                        {isLoadingKeys ? <p className="py-8 text-sm text-muted-foreground" role="status">Loading provider keys...</p> : null}
                        {keyLoadError ? <Alert variant="destructive" role="alert" className="mt-4"><AlertDescription className="flex flex-wrap items-center justify-between gap-3"><span>{keyLoadError}</span><Button variant="outline" size="sm" onClick={() => void loadKeys()}>Retry keys</Button></AlertDescription></Alert> : null}
                        {!organizationReady ? <p className="py-8 text-sm text-muted-foreground">Select an active organization to view provider keys.</p> : null}
                        {organizationReady && !isLoadingKeys && !keyLoadError && visibleKeys.length === 0 ? <EmptyState className="min-h-40" icon={<KeyRound />} title="No keys configured" description="Add a provider key to use your own OpenRouter account." /> : null}
                        {visibleKeys.length > 0 ? (
                            <div className="mt-4 overflow-x-auto">
                                <Table className="min-w-[620px]">
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Provider key</TableHead>
                                            <TableHead>Status</TableHead>
                                            <TableHead>Activity</TableHead>
                                            <TableHead className="text-right">Actions</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                {visibleKeys.map((item) => {
                                    const activeOperation = keyOperation?.id === item.id ? keyOperation.kind : null;
                                    return (
                                        <TableRow key={item.id}>
                                            <TableCell className="max-w-52">
                                                <p className="truncate font-medium text-foreground">{item.label}</p>
                                                <p className="mt-1 font-mono text-xs text-muted-foreground">sk-or-••••{item.suffix}</p>
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={statusVariant(item.status)}>{keyStatusLabel(item.status, item.cooldown_until)}</Badge>
                                                {item.last_error && keyErrorLabel(item.last_error) ? <p className="mt-1 max-w-36 text-xs text-destructive">{keyErrorLabel(item.last_error)}</p> : null}
                                                {item.status === 'cooldown' && item.cooldown_until ? <p className="mt-1 text-xs text-warning">Until {formatDate(item.cooldown_until, true)}</p> : null}
                                            </TableCell>
                                            <TableCell className="text-xs text-muted-foreground">
                                                <p>Added {formatDate(item.created_at)}</p>
                                                <p className="mt-1">Used {formatDate(item.last_used_at, true)}</p>
                                                <p className="mt-1">{item.failure_count ?? 0} failures · Tested {formatDate(item.last_tested_at, true)}</p>
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex justify-end gap-1">
                                                    <Button type="button" variant="outline" size="sm" onClick={() => void handleTestKey(item)} disabled={!canMutate || keyOperation !== null || isLoadingKeys}>
                                                        {activeOperation === 'test' ? <LoaderCircle className="animate-spin" /> : <Check />}
                                                        {activeOperation === 'test' ? 'Testing...' : 'Test'}
                                                    </Button>
                                                    <Button type="button" variant="outline" size="sm" onClick={() => { setReplacementCandidate(item); setLabelOverride(item.label); labelDraftRef.current = item.label; setApiKey(''); setOperationError(null); setNotice(null); }} disabled={!canMutate || keyOperation !== null || isLoadingKeys || isAddingKey}>
                                                        <RefreshCw aria-hidden="true" />Replace
                                                    </Button>
                                                    <Button type="button" variant="ghost" size="icon" onClick={() => setDeleteCandidate(item)} disabled={!canMutate || keyOperation !== null || isLoadingKeys} aria-label={`Delete ${item.label}`} title={`Delete ${item.label}`}>
                                                        {activeOperation === 'delete' ? <LoaderCircle className="animate-spin" /> : <Trash2 />}
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                                    </TableBody>
                                </Table>
                            </div>
                        ) : null}
                    </section>
                </div>

                {operationError ? <Alert variant="destructive" role="alert" className="mt-2"><AlertCircle aria-hidden="true" className="size-4" /><AlertDescription>{operationError}</AlertDescription></Alert> : null}
                {notice ? <Alert variant="success" role="status" className="mt-2"><Check aria-hidden="true" className="size-4" /><AlertDescription>{notice}</AlertDescription></Alert> : null}
            </div>

            <AlertDialog open={deleteCandidate !== null} onOpenChange={(open) => { if (!open) setDeleteCandidate(null); }}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete provider key?</AlertDialogTitle>
                        <AlertDialogDescription>
                            {deleteCandidate ? `Delete ${deleteCandidate.label}? New requests will stop using this key.` : 'This key will no longer be available for new requests.'}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={(event) => { event.preventDefault(); void confirmDelete(); }}>Delete key</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </main>
    );
}
