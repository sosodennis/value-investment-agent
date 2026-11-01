'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowDown, ArrowUp, Check, CircleAlert, KeyRound, Loader2, Power, RefreshCw, Save, Trash2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Combobox } from '@/components/ui/combobox';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { useOrganizationContext } from '@/features/organizations/organization-context';
import {
    addSearchKey, deleteSearchKey, getSearchSettings, replaceSearchKey, setSearchKeyEnabled,
    SearchSettingsApiError, updateSearchSettings,
    type SearchSettings, type SearchProviderSetting,
} from '@/features/search-settings/api';

function requestMessage(error: unknown): string {
    if (error instanceof SearchSettingsApiError && error.status === 503) return 'Search Service is currently unavailable.';
    if (error instanceof SearchSettingsApiError && error.status === 422) return 'The provider rejected this setting or key.';
    if (error instanceof SearchSettingsApiError && error.status === 401) return 'Your session has expired. Sign in again.';
    if (error instanceof SearchSettingsApiError && error.status === 403) return 'You can view Search settings, but only organization owners and admins can change them.';
    if (error instanceof SearchSettingsApiError && error.status === 409) return 'The active organization changed while this request was in progress. Refresh the Search settings.';
    if (error instanceof SearchSettingsApiError && error.status === 404) return 'The active organization or Search settings were not found.';
    return error instanceof Error ? error.message : 'Search settings could not be loaded.';
}

export default function SearchSettingsPage() {
    const router = useRouter();
    const { activeOrganization, isLoading: isLoadingOrganizations } = useOrganizationContext();
    const activeOrganizationId = activeOrganization?.id ?? null;
    const canMutate = activeOrganization?.role === 'owner' || activeOrganization?.role === 'admin';
    const organizationReady = !isLoadingOrganizations && activeOrganizationId !== null;
    const activeOrganizationIdRef = useRef<string | null>(activeOrganizationId);
    const organizationGenerationRef = useRef(0);
    const [data, setData] = useState<SearchSettings | null>(null);
    const [draft, setDraft] = useState<SearchProviderSetting[]>([]);
    const [isInitialLoading, setIsInitialLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [pendingKeyId, setPendingKeyId] = useState<string | null>(null);
    const [keySubmission, setKeySubmission] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [keyError, setKeyError] = useState<string | null>(null);
    const [saveNotice, setSaveNotice] = useState<string | null>(null);
    const [keyNotice, setKeyNotice] = useState<string | null>(null);
    const [provider, setProvider] = useState('');
    const [replacementKeyId, setReplacementKeyId] = useState<string | null>(null);
    const [label, setLabel] = useState('');
    const [apiKey, setApiKey] = useState('');
    const [deleteTarget, setDeleteTarget] = useState<{ id: string; provider: string; label: string } | null>(null);

    useEffect(() => {
        activeOrganizationIdRef.current = activeOrganizationId;
        organizationGenerationRef.current += 1;
        let active = true;
        void Promise.resolve().then(() => {
            if (!active) return;
            setData(null);
            setDraft([]);
            setLoadError(null);
            setSaveError(null);
            setKeyError(null);
            setSaveNotice(null);
            setKeyNotice(null);
            setDeleteTarget(null);
            setReplacementKeyId(null);
            setApiKey('');
            setLabel('');
            setIsRefreshing(false);
            setIsSaving(false);
            setPendingKeyId(null);
            setKeySubmission(false);
            setIsInitialLoading(organizationReady);
        });
        return () => {
            active = false;
        };
    }, [activeOrganizationId, organizationReady]);

    const applySettings = useCallback((result: SearchSettings) => {
        setData(result);
        setDraft(result.settings.providers);
        setProvider((current) => current && result.providers.some((item) => item.provider === current && item.key_required)
            ? current
            : result.providers.find((item) => item.key_required)?.provider ?? '');
    }, []);

    const load = useCallback(async () => {
        const organizationId = activeOrganizationId;
        if (!organizationReady || !organizationId) return;
        const generation = organizationGenerationRef.current;
        const isCurrent = () => activeOrganizationIdRef.current === organizationId && organizationGenerationRef.current === generation;
        setIsRefreshing(true);
        setLoadError(null);
        try {
            const result = await getSearchSettings(organizationId);
            if (!isCurrent()) return;
            applySettings(result);
        } catch (cause) {
            if (!isCurrent()) return;
            if (cause instanceof SearchSettingsApiError && cause.status === 401) router.replace('/login?next=%2Fsettings%2Fsearch');
            setLoadError(requestMessage(cause));
        } finally {
            if (isCurrent()) setIsRefreshing(false);
        }
    }, [activeOrganizationId, applySettings, organizationReady, router]);

    useEffect(() => {
        if (!organizationReady || !activeOrganizationId) return;
        let active = true;
        const organizationId = activeOrganizationId;
        const generation = organizationGenerationRef.current;
        const isCurrent = () => active && activeOrganizationIdRef.current === organizationId && organizationGenerationRef.current === generation;
        void getSearchSettings(organizationId)
            .then((result) => {
                if (isCurrent()) applySettings(result);
            })
            .catch((cause: unknown) => {
                if (!isCurrent()) return;
                if (cause instanceof SearchSettingsApiError && cause.status === 401) router.replace('/login?next=%2Fsettings%2Fsearch');
                setLoadError(requestMessage(cause));
            })
            .finally(() => {
                if (isCurrent()) setIsInitialLoading(false);
            });
        return () => {
            active = false;
        };
    }, [activeOrganizationId, applySettings, organizationReady, router]);

    const providersByName = useMemo(() => new Map(data?.providers.map((item) => [item.provider, item]) ?? []), [data]);
    const sortedDraft = useMemo(() => [...draft].sort((left, right) => left.priority - right.priority), [draft]);
    const keyProviders = useMemo(() => data?.providers.filter((item) => item.key_required) ?? [], [data]);

    function setProviderValue(name: string, update: Partial<SearchProviderSetting>) {
        setDraft((current) => current.map((item) => item.provider === name ? { ...item, ...update } : item));
    }

    async function savePreferences() {
        if (!canMutate || !organizationReady) return;
        const organizationId = activeOrganizationId;
        const generation = organizationGenerationRef.current;
        const isCurrent = () => activeOrganizationIdRef.current === organizationId && organizationGenerationRef.current === generation;
        setIsSaving(true); setSaveError(null); setSaveNotice(null);
        try {
            const result = await updateSearchSettings(organizationId, sortedDraft.map(({ provider: name, enabled }, priority) => ({ provider: name, enabled, priority })));
            if (!isCurrent()) return;
            setData(result); setDraft(result.settings.providers); setSaveNotice('Search provider settings saved.');
        } catch (cause) { if (isCurrent()) setSaveError(requestMessage(cause)); }
        finally { if (isCurrent()) setIsSaving(false); }
    }

    async function saveKey(event: FormEvent<HTMLFormElement>) {
        event.preventDefault(); setKeySubmission(true); setKeyError(null); setKeyNotice(null);
        if (!canMutate || !organizationReady) { setKeySubmission(false); return; }
        const organizationId = activeOrganizationId;
        const generation = organizationGenerationRef.current;
        const isCurrent = () => activeOrganizationIdRef.current === organizationId && organizationGenerationRef.current === generation;
        try {
            const keyInput = { provider, api_key: apiKey, label: label.trim() || `${provider} key` };
            const replacing = replacementKeyId !== null;
            if (replacing) await replaceSearchKey(organizationId, { ...keyInput, key_id: replacementKeyId });
            else await addSearchKey(organizationId, keyInput);
            if (!isCurrent()) return;
            setApiKey(''); setLabel(''); setReplacementKeyId(null);
            await load();
            if (!isCurrent()) return;
            setKeyNotice(replacing ? 'Provider key tested and replaced.' : 'Provider key tested and added.');
        } catch (cause) { if (isCurrent()) setKeyError(requestMessage(cause)); }
        finally { if (isCurrent()) setKeySubmission(false); }
    }

    async function removeKey() {
        if (!deleteTarget || !canMutate || !organizationReady) return;
        const target = deleteTarget;
        const organizationId = activeOrganizationId;
        const generation = organizationGenerationRef.current;
        const isCurrent = () => activeOrganizationIdRef.current === organizationId && organizationGenerationRef.current === generation;
        setPendingKeyId(target.id); setKeyError(null); setKeyNotice(null);
        try {
            await deleteSearchKey(organizationId, target.id);
            if (!isCurrent()) return;
            setDeleteTarget(null);
            await load();
            if (!isCurrent()) return;
            setKeyNotice(`${target.label} was deleted.`);
        } catch (cause) { if (isCurrent()) setKeyError(requestMessage(cause)); }
        finally { if (isCurrent()) setPendingKeyId(null); }
    }

    async function toggleKey(keyId: string, enabled: boolean) {
        if (!canMutate || !organizationReady) return;
        const organizationId = activeOrganizationId;
        const generation = organizationGenerationRef.current;
        const isCurrent = () => activeOrganizationIdRef.current === organizationId && organizationGenerationRef.current === generation;
        setPendingKeyId(keyId); setKeyError(null); setKeyNotice(null);
        try {
            await setSearchKeyEnabled(organizationId, keyId, enabled);
            if (!isCurrent()) return;
            await load();
            if (!isCurrent()) return;
            setKeyNotice(enabled ? 'Provider key enabled.' : 'Provider key disabled.');
        } catch (cause) { if (isCurrent()) setKeyError(requestMessage(cause)); }
        finally { if (isCurrent()) setPendingKeyId(null); }
    }

    function shift(name: string, direction: -1 | 1) {
        const index = sortedDraft.findIndex((item) => item.provider === name);
        const target = index + direction;
        if (index < 0 || target < 0 || target >= sortedDraft.length) return;
        const reordered = [...sortedDraft];
        [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
        setDraft(reordered.map((item, priority) => ({ ...item, priority })));
    }

    if (isLoadingOrganizations || (isInitialLoading && !data)) return <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6" aria-busy="true"><Loader2 className="size-5 animate-spin" /><p className="mt-3 text-sm text-muted-foreground">Loading Search settings…</p></main>;

    return (
        <main className="mx-auto grid w-full max-w-5xl gap-6 px-4 py-6 text-foreground sm:px-6 sm:py-8">
            <header className="flex flex-wrap items-end justify-between gap-4 border-b pb-5">
                <div><p className="text-sm text-muted-foreground">Settings</p><h1 className="mt-1 text-2xl font-semibold">Search providers</h1><p className="mt-2 text-sm text-muted-foreground">Active organization: <span className="font-medium text-foreground">{activeOrganization?.name ?? 'None selected'}</span>{activeOrganization ? ` · ${activeOrganization.role}` : ''}</p></div>
                <Button type="button" variant="outline" onClick={() => void load()} disabled={isRefreshing || !organizationReady} aria-label="Refresh Search settings">
                    <RefreshCw className={isRefreshing ? 'animate-spin' : ''} />Refresh
                </Button>
            </header>

            {!organizationReady ? <Alert role="status"><AlertDescription>Select an active organization to view Search settings.</AlertDescription></Alert> : null}
            {organizationReady && !canMutate ? <Alert role="status"><AlertDescription>You can view and use this organization’s Search configuration. Owners and admins manage provider settings and keys.</AlertDescription></Alert> : null}
            {loadError && <Alert variant="destructive" role="alert"><CircleAlert className="size-4" /><AlertTitle>Could not refresh providers</AlertTitle><AlertDescription className="flex flex-wrap items-center justify-between gap-3"><span>{loadError}</span><Button type="button" variant="outline" size="sm" onClick={() => void load()}>Retry</Button></AlertDescription></Alert>}
            {!data ? <section className="grid justify-items-start gap-3 py-8"><p className="text-sm text-muted-foreground">Provider availability and keys could not be loaded.</p><Button type="button" variant="outline" onClick={() => void load()} disabled={isRefreshing || !organizationReady}>Retry loading settings</Button></section> : <>
                <section aria-labelledby="providers-heading" className="grid gap-4">
                    <div className="flex items-baseline justify-between gap-4"><div><h2 id="providers-heading" className="text-lg font-semibold">Availability and priority</h2><p className="text-sm text-muted-foreground">Choose which providers are enabled and the order to try them.</p></div><Button type="button" onClick={() => void savePreferences()} disabled={!canMutate || isSaving || isRefreshing || sortedDraft.length === 0}>{isSaving ? <Loader2 className="animate-spin" /> : <Save />}Save settings</Button></div>
                    {saveError && <Alert variant="destructive" role="alert"><CircleAlert className="size-4" /><AlertTitle>Settings were not saved</AlertTitle><AlertDescription>{saveError} Your current edits are still available to retry.</AlertDescription></Alert>}
                    {saveNotice && <Alert variant="success"><Check className="size-4" /><AlertDescription>{saveNotice}</AlertDescription></Alert>}
                    {sortedDraft.length === 0 ? <div className="border-y py-8 text-sm text-muted-foreground">No search providers are currently available.</div> : <Card className="overflow-hidden border">
                        <div className="hidden grid-cols-[minmax(10rem,1fr)_8rem_8rem_7rem] gap-4 border-b bg-muted/40 px-4 py-2 text-xs font-medium uppercase text-muted-foreground sm:grid"><span>Provider</span><span>Availability</span><span>Enabled</span><span>Priority</span></div>
                        <div className="divide-y">
                            {sortedDraft.map((item, index) => {
                                const capability = providersByName.get(item.provider);
                                const checkboxId = `provider-enabled-${item.provider}`;
                                return <article key={item.provider} className="grid grid-cols-2 items-center gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-[minmax(10rem,1fr)_8rem_8rem_7rem]">
                                    <div className="col-span-2 min-w-0 sm:col-span-1"><p className="truncate font-medium">{item.provider}</p><p className="text-xs text-muted-foreground">{capability?.operations.join(', ') || 'No operations'}{capability?.key_required ? ' · key required' : ' · no key required'}</p></div>
                                    <div><Badge variant={capability ? 'secondary' : 'outline'}>{capability ? 'Available' : 'Unavailable'}</Badge></div>
                                    <div className="flex items-center gap-2"><Checkbox id={checkboxId} checked={item.enabled} disabled={!canMutate} onCheckedChange={(checked) => setProviderValue(item.provider, { enabled: checked === true })} /><Label htmlFor={checkboxId} className="font-normal">Enabled</Label></div>
                                    <div className="flex items-center gap-1"><Button type="button" variant="ghost" size="icon" onClick={() => shift(item.provider, -1)} disabled={!canMutate || index === 0} aria-label={`Move ${item.provider} up`}><ArrowUp /></Button><span className="w-5 text-center text-sm tabular-nums">{index + 1}</span><Button type="button" variant="ghost" size="icon" onClick={() => shift(item.provider, 1)} disabled={!canMutate || index === sortedDraft.length - 1} aria-label={`Move ${item.provider} down`}><ArrowDown /></Button></div>
                                </article>;
                            })}
                        </div>
                    </Card>}
                </section>

                <Separator />

                <section aria-labelledby="provider-keys-heading" className="grid gap-4">
                    <div><div className="flex items-center gap-2"><KeyRound className="size-4" /><h2 id="provider-keys-heading" className="text-lg font-semibold">Provider keys</h2></div><p className="mt-1 text-sm text-muted-foreground">Keys are shared by this organization and shown only by label and suffix.</p></div>
                    {keyError && <Alert variant="destructive" role="alert"><CircleAlert className="size-4" /><AlertTitle>Key operation failed</AlertTitle><AlertDescription>{keyError}</AlertDescription></Alert>}
                    {keyNotice && <Alert variant="success"><Check className="size-4" /><AlertDescription>{keyNotice}</AlertDescription></Alert>}
                    {sortedDraft.map((item) => {
                        const capability = providersByName.get(item.provider);
                        if (!capability?.key_required) return <p key={item.provider} className="border-b py-3 text-sm text-muted-foreground">{item.provider} does not require a key.</p>;
                        return <Card key={item.provider} className="border">
                            <CardHeader className="pb-3"><CardTitle className="text-base">{item.provider}</CardTitle></CardHeader>
                            <CardContent className="grid gap-3">
                                {item.keys.length === 0 ? <p className="border-y py-4 text-sm text-muted-foreground">No keys configured for this provider.</p> : <div className="divide-y border-y">
                                    {item.keys.map((key) => <div key={key.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                                        <div className="min-w-0"><p className="truncate text-sm font-medium">{key.label} · •••• {key.suffix}</p><p className="text-xs text-muted-foreground">{key.status}{key.cooldown_until ? ` · Cooldown until ${new Date(key.cooldown_until).toLocaleString()}` : ''}{key.last_tested_at ? ` · Tested ${new Date(key.last_tested_at).toLocaleString()}` : ' · Not tested'}{key.last_used_at ? ` · Used ${new Date(key.last_used_at).toLocaleString()}` : ''}{key.failure_count ? ` · ${key.failure_count} recent failures` : ''}</p></div>
                                        <div className="flex items-center gap-1"><Button type="button" variant="outline" size="sm" onClick={() => { setProvider(item.provider); setReplacementKeyId(key.id); setLabel(key.label); setKeyError(null); }} disabled={!canMutate}>Replace</Button><Button type="button" variant="ghost" size="icon" onClick={() => void toggleKey(key.id, !key.enabled)} disabled={!canMutate || pendingKeyId !== null} aria-label={`${key.enabled ? 'Disable' : 'Enable'} ${key.label}`} title={`${key.enabled ? 'Disable' : 'Enable'} provider key`}><Power /></Button><Button type="button" variant="ghost" size="icon" className="text-destructive" onClick={() => setDeleteTarget({ id: key.id, provider: item.provider, label: key.label })} disabled={!canMutate || pendingKeyId !== null} aria-label={`Delete ${key.label}`} title="Delete provider key"><Trash2 /></Button></div>
                                    </div>)}
                                </div>}
                            </CardContent>
                        </Card>;
                    })}
                    {keyProviders.length === 0 ? <div className="border-y py-6 text-sm text-muted-foreground">No configured provider requires an API key.</div> : <form className="grid gap-4 border-t pt-5 sm:grid-cols-2" onSubmit={(event) => void saveKey(event)}>
                        <Field label="Provider" htmlFor="search-key-provider"><Combobox value={provider} onValueChange={(value) => { setProvider(value); setReplacementKeyId(null); setLabel(''); }} options={keyProviders.map((item) => ({ value: item.provider, label: item.provider }))} ariaLabel="Search key provider" placeholder="Select provider" searchPlaceholder="Search providers" disabled={!canMutate} /></Field>
                        <Field label="Key label" htmlFor="search-key-label"><Input id="search-key-label" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Production key" maxLength={128} disabled={!canMutate} /></Field>
                        <Field className="sm:col-span-2" label={replacementKeyId ? 'Replacement API key' : 'Provider API key'} htmlFor="search-provider-api-key" description="The key is tested by the provider before it is stored."><Input id="search-provider-api-key" type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} maxLength={4096} required disabled={!canMutate} /></Field>
                        <div className="flex flex-wrap items-center justify-between gap-3 sm:col-span-2">{replacementKeyId && <Button type="button" variant="ghost" onClick={() => { setReplacementKeyId(null); setLabel(''); setApiKey(''); }} disabled={!canMutate}>Cancel replacement</Button>}<Button className="sm:ml-auto" type="submit" disabled={!canMutate || !apiKey || keySubmission || pendingKeyId !== null || !provider}>{keySubmission ? <Loader2 className="animate-spin" /> : <KeyRound />}{keySubmission ? 'Testing and saving…' : replacementKeyId ? 'Test and replace key' : 'Test and add key'}</Button></div>
                    </form>}
                </section>
            </>}

            <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open && pendingKeyId === null) setDeleteTarget(null); }}>
                <AlertDialogContent>
                    <AlertDialogHeader><AlertDialogTitle>Delete provider key?</AlertDialogTitle><AlertDialogDescription>{deleteTarget ? `Delete “${deleteTarget.label}” for ${deleteTarget.provider}? This removes the key from this organization.` : 'This removes the key from this organization.'}</AlertDialogDescription></AlertDialogHeader>
                    <AlertDialogFooter><AlertDialogCancel disabled={pendingKeyId !== null}>Cancel</AlertDialogCancel><AlertDialogAction disabled={pendingKeyId !== null} onClick={(event) => { event.preventDefault(); void removeKey(); }}>{pendingKeyId ? <Loader2 className="animate-spin" /> : <Trash2 />}Delete key</AlertDialogAction></AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </main>
    );
}
