import { Skeleton } from '@/components/ui/skeleton';

export function FundamentalReportLoading({ title }: { title: string }) {
    return (
        <section role="status" aria-label={title} aria-busy="true" className="@container space-y-4">
            <p className="text-sm font-medium">{title}</p>
            <div className="grid gap-4 @min-[36rem]:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                <Skeleton className="h-32 motion-reduce:animate-none" />
                <div className="space-y-3">
                    <Skeleton className="h-5 w-2/3 motion-reduce:animate-none" />
                    <Skeleton className="h-8 motion-reduce:animate-none" />
                    <Skeleton className="h-4 w-1/2 motion-reduce:animate-none" />
                </div>
            </div>
            <Skeleton className="h-20 motion-reduce:animate-none" />
        </section>
    );
}
