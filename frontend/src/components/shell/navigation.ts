import {
    Activity,
    Building2,
    ChartNoAxesCombined,
    KeyRound,
    LayoutDashboard,
    Settings2,
    Bell,
    type LucideIcon,
} from 'lucide-react';

export type AppRoute = '/' | '/workspace' | '/technical-observability' | '/notifications' | '/settings/llm' | '/settings/search' | '/settings/organization';

export type NavigationItem = {
    href: AppRoute;
    label: string;
    icon: LucideIcon;
};

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
    { href: '/', label: 'Markets', icon: LayoutDashboard },
    { href: '/workspace', label: 'Workspace', icon: ChartNoAxesCombined },
    { href: '/technical-observability', label: 'Observability', icon: Activity },
    { href: '/notifications', label: 'Notifications', icon: Bell },
    { href: '/settings/llm', label: 'LLM settings', icon: Settings2 },
    { href: '/settings/search', label: 'Search settings', icon: KeyRound },
    { href: '/settings/organization', label: 'Organization', icon: Building2 },
];

export function isNavigationItemActive(pathname: string, href: AppRoute) {
    if (href === '/') return pathname === '/';
    return pathname === href || pathname.startsWith(href + '/');
}
