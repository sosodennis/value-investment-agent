'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { useAuth } from './AuthProvider';

const PUBLIC_PATHS = new Set(['/login', '/register']);

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
    const pathname = usePathname();
    const router = useRouter();
    const { loading, user } = useAuth();
    const isPublic = PUBLIC_PATHS.has(pathname);

    useEffect(() => {
        if (!loading && !user && !isPublic) router.replace('/login');
    }, [isPublic, loading, router, user]);

    if (isPublic || (loading && pathname !== '/')) return <>{children}</>;
    if (!user) return null;
    return <>{children}</>;
}
