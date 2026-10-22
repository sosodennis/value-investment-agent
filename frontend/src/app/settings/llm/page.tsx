'use client';

import type { FormEvent } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
    Check,
    CircleAlert,
    KeyRound,
    Loader2,
    Plus,
    RefreshCw,
    ShieldCheck,
    Trash2,
    X,
} from 'lucide-react';

import {
    addLlmProviderKey,
    deleteLlmProviderKey,
    getLlmSettings,
    listLlmProviderKeys,
    LlmSettingsApiError,
    type LlmProviderKey,
    type LlmModelOption,
    testLlmProviderKey,
    updateLlmSettings,
} from '@/lib/llm-settings-api';
import { BeuiSelect } from '@/components/beui/BeuiSelect';

function formatDate(value: string | null | undefined): string {
    if (!value) return 'Unknown date';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
        new Date(value),
    );
}

function formatDateTime(value: string | null | undefined): string {
    if (!value) return 'Never';
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(new Date(value));
}

function keyStatusLabel(
    status: string | undefined,
    cooldownUntil: string | null | undefined,
): string {
    if (cooldownUntil && new Date(cooldownUntil).getTime() > Date.now()) {
        return 'Cooling down';
    }
    switch (status) {
        case 'healthy': return 'Healthy';
        case 'invalid_key': return 'Invalid key';
        case 'unavailable': return 'Unavailable';
        case 'available': return 'Available';
        case 'replacement_grace': return 'Replacing';
        case 'cooldown': return 'Available';
        default: return 'Not tested';
    }
}

function keyErrorLabel(code: string | null | undefined): string | null {
    switch (code) {
        case 'invalid_key': return 'The provider rejected this key.';
        case 'rate_limited': return 'The provider rate limited this key.';
        case 'unavailable': return 'The provider request failed.';
        default: return null;
    }
}

function errorMessage(cause: unknown, fallback: string): string {
    if (!(cause instanceof LlmSettingsApiError)) return fallback;
    switch (cause.message) {
        case 'invalid_key':
            return 'OpenRouter rejected this API key.';
        case 'rate_limited':
            return 'OpenRouter is rate limiting requests. Try again shortly.';
        case 'unavailable':
            return 'The gateway or OpenRouter is currently unavailable.';
        default:
            return cause.message;
    }
}

const LABEL_DRAFT_STORAGE_KEY = 'llm-settings-label-draft';

export default function LlmSettingsPage() {
    const router = useRouter();
    const labelDraftRef = useRef('');
    const redirectingRef = useRef(false);
    const [authenticated, setAuthenticated] = useState(false);
    const [keys, setKeys] = useState<LlmProviderKey[]>([]);
    const [label, setLabel] = useState('');
    const [apiKey, setApiKey] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [models, setModels] = useState<LlmModelOption[]>([]);
    const [selectedModel, setSelectedModel] = useState('openrouter/free');
    const [modelSaving, setModelSaving] = useState(false);

    const redirectToLogin = useCallback((cause: unknown): boolean => {
        if (!(cause instanceof LlmSettingsApiError) || cause.status !== 401) {
            return false;
        }
        if (redirectingRef.current) return true;
        if (typeof window !== 'undefined') {
            const draft = labelDraftRef.current.trim();
            if (draft) {
                window.sessionStorage.setItem(LABEL_DRAFT_STORAGE_KEY, draft);
            } else {
                window.sessionStorage.removeItem(LABEL_DRAFT_STORAGE_KEY);
            }
        }
        redirectingRef.current = true;
        router.replace(`/login?next=${encodeURIComponent('/settings/llm')}`);
        return true;
    }, [router]);

    const loadKeys = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            setKeys(await listLlmProviderKeys());
            setAuthenticated(true);
        } catch (cause) {
            if (!redirectToLogin(cause)) {
                setError(errorMessage(cause, 'Could not load provider keys.'));
            }
            setAuthenticated(false);
        } finally {
            setLoading(false);
        }
    }, [redirectToLogin]);

    const loadModelSettings = useCallback(async () => {
        const settings = await getLlmSettings();
        setModels(settings.models);
        setSelectedModel(settings.selected_model);
    }, []);

    useEffect(() => {
        const draft = window.sessionStorage.getItem(LABEL_DRAFT_STORAGE_KEY);
        if (draft) {
            labelDraftRef.current = draft;
            setLabel(draft);
            window.sessionStorage.removeItem(LABEL_DRAFT_STORAGE_KEY);
        }
        void (async () => {
            setLoading(true);
            setError(null);
            try {
                await Promise.all([loadKeys(), loadModelSettings()]);
            } catch (cause) {
                if (!redirectToLogin(cause)) {
                    setError(errorMessage(cause, 'Could not load provider settings.'));
                }
                setLoading(false);
            }
        })();
    }, [loadKeys, loadModelSettings, redirectToLogin]);

    async function handleModelChange(model: string) {
        setSelectedModel(model);
        setModelSaving(true);
        setError(null);
        setNotice(null);
        try {
            const settings = await updateLlmSettings(model);
            setModels(settings.models);
            setSelectedModel(settings.selected_model);
            setNotice(`Default model changed to ${settings.selected_model}.`);
        } catch (cause) {
            if (!redirectToLogin(cause)) {
                setError(errorMessage(cause, 'Could not update the default model.'));
                await loadModelSettings();
            }
        } finally {
            setModelSaving(false);
        }
    }

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setSubmitting(true);
        setError(null);
        setNotice(null);
        try {
            const created = await addLlmProviderKey({
                label: label.trim() || 'OpenRouter key',
                api_key: apiKey,
            });
            setKeys((current) => [created, ...current]);
            setLabel('');
            labelDraftRef.current = '';
            setApiKey('');
            setNotice(`Key ending in ${created.suffix} passed its test and was added.`);
        } catch (cause) {
            if (!redirectToLogin(cause)) {
                setError(errorMessage(cause, 'Could not add this key.'));
            }
        } finally {
            setSubmitting(false);
        }
    }

    async function handleTest(item: LlmProviderKey) {
        setBusyId(item.id);
        setError(null);
        setNotice(null);
        try {
            const result = await testLlmProviderKey(item.id);
            setNotice(
                result.passed
                    ? `${item.label} is healthy.`
                    : `${item.label} did not pass its connection test.`,
            );
        } catch (cause) {
            if (!redirectToLogin(cause)) {
                setError(errorMessage(cause, 'Could not test this key.'));
            }
        } finally {
            setBusyId(null);
        }
    }

    async function handleDelete(item: LlmProviderKey) {
        if (!window.confirm(`Delete ${item.label}? New requests will stop using this key.`)) {
            return;
        }
        setBusyId(item.id);
        setError(null);
        setNotice(null);
        try {
            await deleteLlmProviderKey(item.id);
            setKeys((current) => current.filter((key) => key.id !== item.id));
            setNotice(`${item.label} was deleted.`);
        } catch (cause) {
            if (!redirectToLogin(cause)) {
                setError(errorMessage(cause, 'Could not delete this key.'));
            }
        } finally {
            setBusyId(null);
        }
    }

    return (
        <main className="min-h-[calc(100vh-4rem)] bg-surface px-6 py-10 text-on-surface md:px-10">
            <div className="mx-auto max-w-5xl">
                <header className="mb-10 flex flex-col gap-5 border-b border-outline-variant/40 pb-8 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-label mb-3">LLM settings</p>
                        <h1 className="font-headline text-3xl">Provider configuration</h1>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-on-surface-variant">
                        <ShieldCheck size={16} className="text-secondary" />
                        Gateway managed
                    </div>
                </header>

                <div className="mb-6 flex items-center gap-3 rounded-lg border border-outline-variant/50 bg-surface-container-low px-5 py-4 text-sm text-on-surface-variant">
                    <ShieldCheck size={17} className="text-secondary" />
                    Signed-in account session
                </div>

                <section className="mb-6 rounded-lg border border-outline-variant/50 bg-surface-container-low p-5" aria-labelledby="model-heading">
                    <div className="mb-5 flex items-start justify-between gap-4">
                        <div>
                            <p className="text-label">Free model routing</p>
                            <h2 id="model-heading" className="mt-2 font-headline text-lg">Default OpenRouter model</h2>
                            <p className="mt-1 max-w-2xl text-sm text-on-surface-variant">
                                Requests use the selected zero-cost model through the managed gateway. The catalogue is loaded from OpenRouter.
                            </p>
                        </div>
                        {modelSaving ? <Loader2 size={17} className="mt-1 animate-spin text-primary-container" aria-label="Saving model" /> : null}
                    </div>
                    <BeuiSelect
                        value={selectedModel}
                        options={models.map((model) => ({ value: model.id, label: model.name, description: model.description }))}
                        onValueChange={(model) => void handleModelChange(model)}
                        disabled={!authenticated || modelSaving || models.length === 0}
                        aria-label="Default OpenRouter model"
                        placeholder={models.length === 0 ? 'Loading free models...' : 'Select a free model'}
                    />
                    <p className="mt-3 font-mono text-[11px] text-on-surface-variant">
                        Selected: {selectedModel}
                    </p>
                </section>

                <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
                    <form
                        onSubmit={handleSubmit}
                        className="rounded-lg border border-outline-variant/50 bg-surface-container-low p-5"
                    >
                        <div className="mb-6 flex items-center gap-3">
                            <div className="rounded bg-primary-container/10 p-2 text-primary-container">
                                <KeyRound size={18} />
                            </div>
                            <h2 className="font-headline text-lg">Add a key</h2>
                        </div>
                        <label htmlFor="key-label" className="text-label">
                            Label
                        </label>
                        <input
                            id="key-label"
                            value={label}
                            onChange={(event) => {
                                labelDraftRef.current = event.target.value;
                                setLabel(event.target.value);
                            }}
                            placeholder="Primary research key"
                            className="mt-2 mb-5 w-full rounded border border-outline-variant bg-surface px-3 py-2 text-sm outline-none focus:border-primary-container"
                            maxLength={80}
                        />
                        <label htmlFor="openrouter-key" className="text-label">
                            OpenRouter API key
                        </label>
                        <input
                            id="openrouter-key"
                            type="password"
                            value={apiKey}
                            onChange={(event) => setApiKey(event.target.value)}
                            placeholder="sk-or-v1-..."
                            className="mt-2 w-full rounded border border-outline-variant bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-primary-container"
                            minLength={20}
                            maxLength={500}
                            autoComplete="off"
                            required
                        />
                        <button
                            type="submit"
                            disabled={submitting || !authenticated || !apiKey}
                            className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded bg-primary-container px-4 py-2.5 text-sm font-semibold text-on-primary transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {submitting ? (
                                <Loader2 size={16} className="animate-spin" />
                            ) : (
                                <Plus size={16} />
                            )}
                            {submitting ? 'Testing and adding...' : 'Test and add key'}
                        </button>
                    </form>

                    <section
                        className="rounded-lg border border-outline-variant/50 bg-surface-container-low p-5"
                        aria-labelledby="keys-heading"
                    >
                        <div className="mb-6 flex items-center justify-between">
                            <h2 id="keys-heading" className="font-headline text-lg">
                                Configured keys
                            </h2>
                            <button
                                type="button"
                                onClick={() => void loadKeys()}
                                disabled={loading || !authenticated}
                                className="rounded p-2 text-on-surface-variant transition hover:bg-surface-container hover:text-on-surface disabled:opacity-40"
                                aria-label="Refresh keys"
                                title="Refresh keys"
                            >
                                {loading ? (
                                    <Loader2 size={16} className="animate-spin" />
                                ) : (
                                    <RefreshCw size={16} />
                                )}
                            </button>
                        </div>

                        {keys.length === 0 ? (
                            <div className="flex min-h-48 flex-col items-center justify-center border border-dashed border-outline-variant/50 px-5 text-center">
                                <KeyRound size={24} className="mb-3 text-on-surface-variant" />
                                <p className="text-sm">
                                    {loading ? 'Loading keys...' : 'No keys configured'}
                                </p>
                            </div>
                        ) : (
                            <div className="divide-y divide-outline-variant/30">
                                {keys.map((item) => (
                                    <div
                                        key={item.id}
                                        className="flex flex-col gap-4 py-4 first:pt-0 sm:flex-row sm:items-center sm:justify-between"
                                    >
                                        <div className="min-w-0">
                                            <div className="flex items-center gap-2">
                                                <p className="truncate text-sm font-semibold">
                                                    {item.label}
                                                </p>
                                                <span className="inline-flex items-center gap-1 rounded-full bg-secondary/10 px-2 py-0.5 text-[10px] text-secondary">
                                                    {item.status === 'healthy' ? (
                                                        <Check size={11} />
                                                    ) : (
                                                        <CircleAlert size={11} />
                                                    )}
                                                    {keyStatusLabel(item.status, item.cooldown_until)}
                                                </span>
                                            </div>
                                            <p className="mt-1 font-mono text-xs text-on-surface-variant">
                                                sk-or-••••{item.suffix}
                                            </p>
                                            <p className="mt-1 text-[11px] text-on-surface-variant">
                                                Added {formatDate(item.created_at)} · {item.fingerprint}
                                            </p>
                                            <p className="mt-1 text-[11px] text-on-surface-variant">
                                                Last used {formatDateTime(item.last_used_at)} ·{' '}
                                                {item.failure_count ?? 0} failures since last success
                                            </p>
                                            {item.cooldown_until && new Date(item.cooldown_until).getTime() > Date.now() && (
                                                <p className="mt-1 text-[11px] text-amber-300">
                                                    Cooldown ends {formatDateTime(item.cooldown_until)}
                                                </p>
                                            )}
                                            {item.last_error && (
                                                <p className="mt-1 text-[11px] text-error">
                                                    {keyErrorLabel(item.last_error)}
                                                </p>
                                            )}
                                            <p className="mt-1 text-[11px] text-on-surface-variant">
                                                Last tested {formatDateTime(item.last_tested_at)}
                                            </p>
                                        </div>
                                        <div className="flex shrink-0 items-center gap-1">
                                            <button
                                                type="button"
                                                onClick={() => void handleTest(item)}
                                                disabled={busyId !== null}
                                                className="rounded px-3 py-1.5 text-xs text-on-surface-variant transition hover:bg-surface-container hover:text-on-surface disabled:opacity-40"
                                            >
                                                {busyId === item.id ? (
                                                    <Loader2 size={14} className="animate-spin" />
                                                ) : (
                                                    'Test'
                                                )}
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => void handleDelete(item)}
                                                disabled={busyId !== null}
                                                className="rounded p-2 text-on-surface-variant transition hover:bg-error/10 hover:text-error disabled:opacity-40"
                                                aria-label={`Delete ${item.label}`}
                                                title={`Delete ${item.label}`}
                                            >
                                                {busyId === item.id ? (
                                                    <Loader2 size={14} className="animate-spin" />
                                                ) : (
                                                    <Trash2 size={15} />
                                                )}
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </section>
                </div>

                {(error || notice) && (
                    <div
                        role={error ? 'alert' : 'status'}
                        className={`mt-6 flex items-start gap-3 rounded border px-4 py-3 text-sm ${
                            error
                                ? 'border-error/40 bg-error/10 text-rose-200'
                                : 'border-secondary/40 bg-secondary/10 text-emerald-200'
                        }`}
                    >
                        {error ? (
                            <X size={17} className="mt-0.5 shrink-0" />
                        ) : (
                            <Check size={17} className="mt-0.5 shrink-0" />
                        )}
                        <p>{error || notice}</p>
                    </div>
                )}
            </div>
        </main>
    );
}
