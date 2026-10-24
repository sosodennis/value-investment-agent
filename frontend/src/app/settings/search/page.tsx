'use client';

import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowDown, ArrowUp, Check, CircleAlert, KeyRound, Loader2, RefreshCw, Save, Trash2 } from 'lucide-react';
import { BeuiSelect } from '@/components/beui/BeuiSelect';
import {
    addSearchKey, deleteSearchKey, getSearchSettings, replaceSearchKey,
    SearchSettingsApiError, updateSearchSettings,
    type SearchSettings, type SearchProviderSetting,
} from '@/lib/search-settings-api';

function requestMessage(error: unknown): string {
    if (error instanceof SearchSettingsApiError && error.status === 503) return 'Search Service is currently unavailable.';
    if (error instanceof SearchSettingsApiError && error.status === 422) return 'The provider rejected this setting or key.';
    if (error instanceof SearchSettingsApiError && error.status === 401) return 'Your session has expired. Sign in again.';
    return error instanceof Error ? error.message : 'Search settings could not be loaded.';
}

export default function SearchSettingsPage() {
    const router = useRouter();
    const [data, setData] = useState<SearchSettings | null>(null);
    const [draft, setDraft] = useState<SearchProviderSetting[]>([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [busyProvider, setBusyProvider] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [provider, setProvider] = useState('');
    const [replacementKeyId, setReplacementKeyId] = useState<string | null>(null);
    const [label, setLabel] = useState('');
    const [apiKey, setApiKey] = useState('');

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await getSearchSettings();
            setData(result);
            setDraft(result.settings.providers);
            setProvider((current) => current && result.providers.some((item) => item.provider === current && item.key_required)
                ? current
                : result.providers.find((item) => item.key_required)?.provider ?? '');
        } catch (cause) {
            if (cause instanceof SearchSettingsApiError && cause.status === 401) router.replace('/login?next=%2Fsettings%2Fsearch');
            setError(requestMessage(cause));
        } finally { setLoading(false); }
    }, [router]);

    useEffect(() => { void load(); }, [load]);

    const providersByName = useMemo(() => new Map(data?.providers.map((item) => [item.provider, item]) ?? []), [data]);
    const sortedDraft = useMemo(() => [...draft].sort((left, right) => left.priority - right.priority), [draft]);
    const setProviderValue = (name: string, update: Partial<SearchProviderSetting>) => {
        setDraft((current) => current.map((item) => item.provider === name ? { ...item, ...update } : item));
    };

    async function savePreferences() {
        setSaving(true); setError(null); setNotice(null);
        try {
            const result = await updateSearchSettings(draft.map(({ provider: name, enabled }, priority) => ({ provider: name, enabled, priority })));
            setData(result); setDraft(result.settings.providers); setNotice('Search provider settings saved.');
        } catch (cause) { setError(requestMessage(cause)); }
        finally { setSaving(false); }
    }

    async function saveKey(event: FormEvent<HTMLFormElement>) {
        event.preventDefault(); setBusyProvider(provider); setError(null); setNotice(null);
        try {
            const keyInput = { provider, api_key: apiKey, label: label.trim() || `${provider} key` };
            if (replacementKeyId) await replaceSearchKey({ ...keyInput, key_id: replacementKeyId });
            else await addSearchKey(keyInput);
            setApiKey(''); setLabel(''); setReplacementKeyId(null);
            await load();
            setNotice(replacementKeyId ? 'Provider key replaced after a successful test.' : 'Provider key tested and added.');
        } catch (cause) { setError(requestMessage(cause)); }
        finally { setBusyProvider(null); }
    }

    async function removeKey(item: SearchProviderSetting) {
        if (!item.key || !window.confirm(`Delete the ${item.key.label} key?`)) return;
        setBusyProvider(item.provider); setError(null); setNotice(null);
        try { await deleteSearchKey(item.key.id); await load(); setNotice(`${item.key.label} was deleted.`); }
        catch (cause) { setError(requestMessage(cause)); }
        finally { setBusyProvider(null); }
    }

    function shift(name: string, direction: -1 | 1) {
        const index = sortedDraft.findIndex((item) => item.provider === name);
        const target = index + direction;
        if (index < 0 || target < 0 || target >= sortedDraft.length) return;
        const reordered = [...sortedDraft];
        [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
        setDraft(reordered.map((item, priority) => ({ ...item, priority })));
    }

    if (loading && !data) return <main className="mx-auto max-w-5xl px-6 py-12" aria-busy="true"><Loader2 className="animate-spin" size={20} /><p className="mt-3 text-sm text-on-surface-variant">Loading Search settings…</p></main>;

    return (
        <main className="mx-auto max-w-5xl px-6 py-10 text-on-surface">
            <header className="flex flex-wrap items-end justify-between gap-4 border-b border-outline-variant pb-5">
                <div><p className="text-xs font-semibold uppercase text-on-surface-variant">Settings</p><h1 className="mt-1 text-2xl font-semibold">Search providers</h1></div>
                <button type="button" onClick={() => void load()} disabled={loading} aria-label="Refresh Search settings" title="Refresh Search settings" className="rounded border border-outline-variant p-2 hover:bg-surface-container disabled:opacity-50"><RefreshCw size={17} /></button>
            </header>
            {error && <div role="alert" className="mt-5 flex gap-2 border-l-2 border-error px-3 py-2 text-sm text-error"><CircleAlert size={17} />{error}</div>}
            {notice && <p role="status" className="mt-5 flex items-center gap-2 text-sm text-primary-container"><Check size={16} />{notice}</p>}
            {!data ? <div className="py-10 text-sm text-on-surface-variant">{error ? 'Search settings are unavailable.' : 'No Search settings are available.'}</div> : <>
                {sortedDraft.length === 0 ? <p className="py-8 text-sm text-on-surface-variant">No search providers are currently available.</p> : <section aria-label="Provider availability and priority" className="mt-6">
                    <div className="hidden grid-cols-[minmax(8rem,1fr)_7rem_8rem_5rem] gap-3 border-b border-outline-variant px-2 pb-2 text-xs font-semibold uppercase text-on-surface-variant sm:grid"><span>Provider</span><span>Available</span><span>Enabled</span><span>Order</span></div>
                    {sortedDraft.map((item, index) => {
                        const capability = providersByName.get(item.provider);
                        return <div key={item.provider} className="grid grid-cols-2 items-center gap-3 border-b border-outline-variant/60 px-2 py-3 text-sm sm:grid-cols-[minmax(8rem,1fr)_7rem_8rem_5rem]">
                            <div className="col-span-2 min-w-0 sm:col-span-1"><p className="truncate font-medium">{item.provider}</p><p className="text-xs text-on-surface-variant">{capability?.operations.join(', ') || 'No operations'}{capability?.key_required ? ' · key required' : ' · no key required'}</p></div>
                            <span className={capability ? 'text-primary-container' : 'text-on-surface-variant'}>{capability ? 'Available' : 'Unavailable'}</span>
                            <label className="flex items-center gap-2"><input type="checkbox" checked={item.enabled} onChange={(event) => setProviderValue(item.provider, { enabled: event.target.checked })} aria-label={`Enable ${item.provider}`} />Enabled</label>
                            <div className="flex gap-1"><button type="button" onClick={() => shift(item.provider, -1)} disabled={index === 0} aria-label={`Move ${item.provider} up`} className="rounded p-1 hover:bg-surface-container disabled:opacity-30"><ArrowUp size={15} /></button><button type="button" onClick={() => shift(item.provider, 1)} disabled={index === sortedDraft.length - 1} aria-label={`Move ${item.provider} down`} className="rounded p-1 hover:bg-surface-container disabled:opacity-30"><ArrowDown size={15} /></button></div>
                        </div>;
                    })}
                    <div className="mt-4 flex justify-end"><button type="button" onClick={() => void savePreferences()} disabled={saving} className="inline-flex items-center gap-2 rounded bg-primary-container px-4 py-2 text-sm font-semibold text-on-primary-container disabled:opacity-50">{saving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}Save settings</button></div>
                </section>}
                <section className="mt-10 border-t border-outline-variant pt-6" aria-labelledby="provider-keys-heading">
                    <div className="flex items-center gap-2"><KeyRound size={18} /><h2 id="provider-keys-heading" className="text-lg font-semibold">Provider keys</h2></div>
                    <div className="mt-4 divide-y divide-outline-variant/60">
                        {sortedDraft.map((item) => {
                            const capability = providersByName.get(item.provider);
                            if (!capability?.key_required) return <p key={item.provider} className="py-3 text-sm text-on-surface-variant">{item.provider} does not require a key.</p>;
                            return <div key={item.provider} className="flex flex-wrap items-center justify-between gap-3 py-3">
                                <div><p className="font-medium">{item.provider}</p>{item.key ? <p className="text-sm text-on-surface-variant">{item.key.label} · •••• {item.key.suffix} · {item.key.status}{item.key.last_tested_at ? ` · Tested ${new Date(item.key.last_tested_at).toLocaleString()}` : ' · Not tested'}{item.key.failure_count ? ` · ${item.key.failure_count} recent failures` : ''}</p> : <p className="text-sm text-on-surface-variant">No key configured</p>}</div>
                                {item.key && <button type="button" onClick={() => { setProvider(item.provider); setReplacementKeyId(item.key?.id ?? null); setLabel(item.key?.label ?? ''); }} className="rounded border border-outline-variant px-3 py-2 text-sm hover:bg-surface-container">Replace</button>}
                                {item.key && <button type="button" onClick={() => void removeKey(item)} disabled={busyProvider === item.provider} aria-label={`Delete ${item.key.label}`} title="Delete provider key" className="rounded p-2 text-error hover:bg-error/10 disabled:opacity-50"><Trash2 size={17} /></button>}
                            </div>;
                        })}
                    </div>
                    {data.providers.some((item) => item.key_required) && <form className="mt-5 grid grid-cols-1 gap-2 md:grid-cols-[minmax(9rem,1fr)_minmax(10rem,1.4fr)_minmax(10rem,1.4fr)_auto]" onSubmit={(event) => void saveKey(event)}>
                        <BeuiSelect value={provider} options={data.providers.filter((item) => item.key_required).map((item) => ({ value: item.provider, label: item.provider }))} onValueChange={(value) => { setProvider(value); setReplacementKeyId(null); setLabel(''); }} aria-label="Search key provider" />
                        <input aria-label="Search key label" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Key label" maxLength={128} className="min-w-0 rounded border border-outline-variant bg-surface px-3 py-2 text-sm" />
                        <input aria-label="Search provider API key" type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={replacementKeyId ? 'Replacement key' : 'Provider API key'} maxLength={4096} required className="min-w-0 rounded border border-outline-variant bg-surface px-3 py-2 text-sm" />
                        <button type="submit" disabled={!apiKey || busyProvider !== null || !provider} className="rounded border border-outline-variant px-3 py-2 text-sm font-medium hover:bg-surface-container disabled:opacity-50">{busyProvider ? 'Testing…' : replacementKeyId ? 'Test and replace' : 'Test and add'}</button>
                    </form>}
                </section>
            </>}
        </main>
    );
}
