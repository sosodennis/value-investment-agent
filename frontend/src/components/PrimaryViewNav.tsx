import Link from 'next/link';

type PrimaryViewNavProps = {
    currentView: 'workspace' | 'technical-observability';
};

type NavItem = {
    href: string;
    label: string;
    value: PrimaryViewNavProps['currentView'];
};

const NAV_ITEMS: NavItem[] = [
    { href: '/', label: 'Analysis Workspace', value: 'workspace' },
    {
        href: '/technical-observability',
        label: 'Technical Observability',
        value: 'technical-observability',
    },
];

export function PrimaryViewNav({ currentView }: PrimaryViewNavProps) {
    return (
        <nav
            className="hidden xl:flex items-center gap-3 rounded-2xl border border-white/6 bg-slate-950/70 p-1 shadow-[0_18px_60px_rgba(2,6,23,0.28)]"
            aria-label="Primary Views"
        >
            {NAV_ITEMS.map((item) => {
                const isActive = item.value === currentView;
                return (
                    <Link
                        key={item.href}
                        href={item.href}
                        className={`min-h-11 rounded-xl px-4 py-2.5 text-[11px] font-black uppercase tracking-[0.22em] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/70 ${
                            isActive
                                ? 'bg-cyan-500/14 text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.3)]'
                                : 'text-slate-400 hover:bg-white/4 hover:text-slate-100'
                        }`}
                        aria-current={isActive ? 'page' : undefined}
                    >
                        {item.label}
                    </Link>
                );
            })}
        </nav>
    );
}
