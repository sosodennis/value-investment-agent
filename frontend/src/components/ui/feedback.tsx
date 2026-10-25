import { CircleAlert, CircleCheck, Info } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

type FeedbackTone = 'success' | 'error' | 'info';

const feedbackStyles: Record<
    FeedbackTone,
    { className: string; Icon: LucideIcon; role: 'status' | 'alert' }
> = {
    success: {
        className: 'text-success',
        Icon: CircleCheck,
        role: 'status',
    },
    error: {
        className: 'text-destructive',
        Icon: CircleAlert,
        role: 'alert',
    },
    info: {
        className: 'text-muted-foreground',
        Icon: Info,
        role: 'status',
    },
};

export function Feedback({
    tone = 'info',
    className,
    children,
}: {
    tone?: FeedbackTone;
    className?: string;
    children: React.ReactNode;
}) {
    const { className: toneClassName, Icon, role } = feedbackStyles[tone];
    return (
        <div className={cn('flex items-start gap-2 text-sm', toneClassName, className)} role={role}>
            <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div>{children}</div>
        </div>
    );
}
