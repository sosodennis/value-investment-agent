import {
    Activity,
    ChartNoAxesCombined,
    KeyRound,
    LayoutDashboard,
    Settings2,
    type LucideIcon,
} from 'lucide-react';

export type AppRoute = '/' | '/workspace' | '/technical-observability' | '/settings/llm' | '/settings/search';

export type NavigationItem = {
    href: AppRoute;
    label: string;
    icon: LucideIcon;
};

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
    { href: '/', label: 'Markets', icon: LayoutDashboard },
    { href: '/workspace', label: 'Workspace', icon: ChartNoAxesCombined },
    { href: '/technical-observability', label: 'Observability', icon: Activity },
    { href: '/settings/llm', label: 'LLM settings', icon: Settings2 },
    { href: '/settings/search', label: 'Search settings', icon: KeyRound },
];

export function isNavigationItemActive(pathname: string, href: AppRoute) {
    if (href === '/') return pathname === '/';
    return pathname === href || pathname.startsWith(href + '/');
}
