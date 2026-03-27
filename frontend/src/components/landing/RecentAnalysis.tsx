import { Brain, BarChart3 } from 'lucide-react';

export type RecentAnalysisItem = {
    id: string;
    title: string;
    summary: string;
    time: string;
    icon: 'stats' | 'insights';
};

type RecentAnalysisProps = {
    items: RecentAnalysisItem[];
};

const iconFor = (icon: RecentAnalysisItem['icon']) => {
    if (icon === 'insights') {
        return <Brain size={18} className="text-tertiary-fixed-dim" />;
    }
    return <BarChart3 size={18} className="text-primary-container" />;
};

export function RecentAnalysis({ items }: RecentAnalysisProps) {
    return (
        <div className="pt-8 space-y-6">
            <div className="flex items-center justify-between px-2">
                <h2 className="text-xs uppercase tracking-[0.2em] font-bold text-outline">
                    Recent Analysis
                </h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-left">
                {items.map((item) => (
                    <div
                        key={item.id}
                        className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 hover:border-primary-container/30 transition-colors flex gap-4"
                    >
                        <div className="h-12 w-12 rounded bg-surface-container-high flex items-center justify-center">
                            {iconFor(item.icon)}
                        </div>
                        <div>
                            <h4 className="font-bold text-primary-fixed">{item.title}</h4>
                            <p className="text-xs text-on-surface-variant mt-1 line-clamp-1">
                                {item.summary}
                            </p>
                            <span className="text-[10px] text-outline mt-2 block uppercase tracking-tighter tabular-nums">
                                {item.time}
                            </span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
