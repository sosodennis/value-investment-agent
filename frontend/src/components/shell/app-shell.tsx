'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useTheme } from 'next-themes';
import { Building2, LogOut, Menu, Moon, Sun, Laptop, RefreshCw, Sparkles, UserRound } from 'lucide-react';
import { useAuth } from '@/components/auth/AuthProvider';
import { useOrganizationContext } from '@/features/organizations/organization-context';
import { Button } from '@/components/ui/button';
import { Combobox } from '@/components/ui/combobox';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
    Sheet,
    SheetClose,
    SheetContent,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
} from '@/components/ui/sheet';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { NAVIGATION_ITEMS, isNavigationItemActive } from './navigation';

function NavigationLinks({ closeOnNavigate = false }: { closeOnNavigate?: boolean }) {
    const pathname = usePathname();

    return (
        <nav aria-label="Primary navigation" className="grid gap-1">
            {NAVIGATION_ITEMS.map((item) => {
                const active = isNavigationItemActive(pathname, item.href);
                const Icon = item.icon;
                const link = (
                    <Link
                        href={item.href}
                        aria-current={active ? 'page' : undefined}
                        className={[
                            'flex min-h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
                            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                            active
                                ? 'bg-primary/12 text-primary'
                                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                        ].join(' ')}
                    >
                        <Icon aria-hidden="true" className="size-4 shrink-0" />
                        <span>{item.label}</span>
                    </Link>
                );

                return closeOnNavigate ? (
                    <SheetClose asChild key={item.href}>
                        {link}
                    </SheetClose>
                ) : (
                    <React.Fragment key={item.href}>{link}</React.Fragment>
                );
            })}
        </nav>
    );
}

function ThemeMenu() {
    const { setTheme, theme } = useTheme();

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger asChild>
                    <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="relative" aria-label="Change color theme">
                            <Sun className="size-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
                            <Moon className="absolute size-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
                        </Button>
                    </DropdownMenuTrigger>
                </TooltipTrigger>
                <TooltipContent>Change color theme</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuLabel>Appearance</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
                    <DropdownMenuRadioItem value="light">
                        <Sun aria-hidden="true" className="mr-2 size-4" />
                        Light
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="dark">
                        <Moon aria-hidden="true" className="mr-2 size-4" />
                        Dark
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="system">
                        <Laptop aria-hidden="true" className="mr-2 size-4" />
                        System
                    </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

function OrganizationSwitcher() {
    const {
        organizations,
        activeOrganization,
        error,
        isLoading,
        isSelecting,
        refresh,
        selectOrganization,
    } = useOrganizationContext();

    if (isLoading && organizations.length === 0) {
        return (
            <div className="hidden min-w-0 items-center gap-2 text-sm text-muted-foreground sm:flex" role="status">
                <Building2 aria-hidden="true" className="size-4 shrink-0" />
                <span className="max-w-36 truncate">Loading organization...</span>
            </div>
        );
    }

    return (
        <div className="flex min-w-0 items-center gap-2">
            <Building2 aria-hidden="true" className="hidden size-4 shrink-0 text-muted-foreground sm:block" />
            {organizations.length > 0 ? (
                <Combobox
                    value={activeOrganization?.id}
                    onValueChange={(organizationId) => {
                        if (organizationId) void selectOrganization(organizationId);
                    }}
                    options={organizations.map((organization) => ({
                        value: organization.id,
                        label: `${organization.name} (${organization.role})`,
                        keywords: [organization.name, organization.role],
                    }))}
                    ariaLabel="Active organization"
                    placeholder="Select organization"
                    searchPlaceholder="Search organizations"
                    emptyMessage="No organizations found."
                    disabled={isLoading || isSelecting}
                    className="h-9 w-36 max-w-[42vw] border-border/70 bg-background/70 text-xs sm:w-48 sm:text-sm"
                />
            ) : null}
            {error ? (
                <div className="hidden items-center gap-1 sm:flex" role="alert">
                    <span className="max-w-40 truncate text-sm text-destructive">Organization unavailable</span>
                    <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Retry organization context"
                        onClick={() => void refresh()}
                    >
                        <RefreshCw aria-hidden="true" className="size-4" />
                    </Button>
                </div>
            ) : null}
        </div>
    );
}

function AccountMenu() {
    const { user, signOut } = useAuth();
    const router = useRouter();
    const [error, setError] = React.useState<string | null>(null);
    const [isSigningOut, setIsSigningOut] = React.useState(false);

    async function handleSignOut() {
        setError(null);
        setIsSigningOut(true);
        try {
            await signOut();
            router.replace('/login');
        } catch {
            setError('Could not sign out. Try again.');
        } finally {
            setIsSigningOut(false);
        }
    }

    if (!user) return null;

    return (
        <div className="relative flex items-center">
            <DropdownMenu>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <DropdownMenuTrigger asChild>
                            <Button
                                variant="ghost"
                                className="max-w-48 justify-start px-2"
                                aria-label={'Account menu for ' + user.email}
                            >
                                <span className="hidden max-w-36 truncate sm:inline">{user.email}</span>
                                <UserRound aria-hidden="true" className="size-4 shrink-0" />
                            </Button>
                        </DropdownMenuTrigger>
                    </TooltipTrigger>
                    <TooltipContent>Account</TooltipContent>
                </Tooltip>
                <DropdownMenuContent align="end" className="w-56">
                    <DropdownMenuLabel className="max-w-52 truncate">{user.email}</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem disabled={isSigningOut} onSelect={() => void handleSignOut()}>
                        <LogOut aria-hidden="true" />
                        Sign out
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            {error ? (
                <p role="alert" className="absolute right-0 top-12 z-50 w-56 rounded-md bg-destructive px-3 py-2 text-sm text-destructive-foreground shadow-md">
                    {error}
                </p>
            ) : null}
        </div>
    );
}

function MobileNavigation() {
    return (
        <Sheet>
            <Tooltip>
                <TooltipTrigger asChild>
                    <SheetTrigger asChild>
                        <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation">
                            <Menu aria-hidden="true" />
                        </Button>
                    </SheetTrigger>
                </TooltipTrigger>
                <TooltipContent>Open navigation</TooltipContent>
            </Tooltip>
            <SheetContent side="left" className="md:hidden">
                <SheetHeader>
                    <SheetTitle>FinanceAI Lab</SheetTitle>
                </SheetHeader>
                <NavigationLinks closeOnNavigate />
            </SheetContent>
        </Sheet>
    );
}

function AppHeader() {
    const { loading } = useAuth();
    const pathname = usePathname();
    const isAuthPage = pathname === '/login' || pathname === '/register';

    return (
        <header className="sticky top-0 z-40 flex h-16 items-center justify-between bg-card px-3 sm:px-5">
            <div className="flex min-w-0 items-center gap-2">
                {!isAuthPage && !loading ? <MobileNavigation /> : null}
                <Link
                    href="/"
                    className="inline-flex items-center gap-2 rounded-sm text-base font-bold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                    <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                        <Sparkles aria-hidden="true" className="size-4" />
                    </span>
                    <span className="truncate">FinanceAI Lab</span>
                </Link>
                {!isAuthPage && !loading ? <OrganizationSwitcher /> : null}
            </div>
            {!isAuthPage ? (
                <div className="flex shrink-0 items-center gap-1">
                    <ThemeMenu />
                    {!loading ? <AccountMenu /> : null}
                </div>
            ) : (
                <ThemeMenu />
            )}
        </header>
    );
}

export function AppShell({ children }: { children: React.ReactNode }) {
    const pathname = usePathname();
    const isAuthPage = pathname === '/login' || pathname === '/register';
    const { loading, user } = useAuth();

    if (isAuthPage) {
        return (
            <>
                <AppHeader />
                <div id="main-content" tabIndex={-1}>{children}</div>
            </>
        );
    }

    if (loading || !user) return null;

    return (
        <div className="min-h-screen bg-background text-foreground">
            <a
                href="#main-content"
                className="sr-only z-50 rounded-md bg-popover px-3 py-2 text-sm text-popover-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
            >
                Skip to main content
            </a>
            <AppHeader />
            <div className="flex min-h-[calc(100vh-4rem)]">
                <aside className="hidden w-60 shrink-0 bg-sidebar px-3 py-5 md:block">
                    <NavigationLinks />
                </aside>
                <div id="main-content" tabIndex={-1} className="min-w-0 flex-1">
                    {children}
                </div>
            </div>
        </div>
    );
}
