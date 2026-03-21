import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { HeaderBar } from './HeaderBar';

vi.mock('next/link', () => ({
    default: ({
        children,
        href,
        ...rest
    }: {
        children: React.ReactNode;
        href: string;
    }) => (
        <a href={href} {...rest}>
            {children}
        </a>
    ),
}));

describe('HeaderBar', () => {
    it('renders primary navigation alongside workspace actions', () => {
        render(
            <HeaderBar
                systemStatus="online"
                activeAgents={3}
                stage="Running"
                ticker="AAPL"
                onTickerChange={() => {}}
                onStartAnalysis={() => {}}
                onShowHistory={() => {}}
                isLoading={false}
                currentView="workspace"
            />
        );

        expect(screen.getByRole('link', { name: 'Analysis Workspace' })).not.toBeNull();
        expect(
            screen.getByRole('link', { name: 'Technical Observability' })
        ).not.toBeNull();
        expect(screen.getByRole('button', { name: 'Start Analysis' })).not.toBeNull();
    });
});
