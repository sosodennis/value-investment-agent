import { cn } from '@/lib/cn';

export function EmptyState({
    className,
    icon,
    title,
    description,
    action,
}: {
    className?: string;
    icon?: React.ReactNode;
    title: string;
    description?: React.ReactNode;
    action?: React.ReactNode;
}) {
    return (
        <section
            className={cn('flex min-h-40 flex-col items-center justify-center gap-3 text-center', className)}
            aria-label={title}
        >
            {icon ? <div className="text-muted-foreground [&_svg]:size-5">{icon}</div> : null}
            <div className="grid gap-1">
                <h2 className="text-base font-semibold text-foreground">{title}</h2>
                {description ? <p className="max-w-lg text-sm text-muted-foreground">{description}</p> : null}
            </div>
            {action}
        </section>
    );
}
