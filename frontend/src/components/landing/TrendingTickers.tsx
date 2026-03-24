import { TrendingDown, TrendingUp, Minus } from 'lucide-react';

type Trend = 'up' | 'down' | 'flat';

export type TrendingTicker = {
    symbol: string;
    name: string;
    price: string;
    change: string;
    trend: Trend;
};

type TrendingTickersProps = {
    tickers: TrendingTicker[];
    onSelectTicker?: (symbol: string) => void;
};

const trendIcon = (trend: Trend) => {
    if (trend === 'up') return <TrendingUp size={14} className="text-secondary" />;
    if (trend === 'down')
        return <TrendingDown size={14} className="text-error" />;
    return <Minus size={14} className="text-outline" />;
};

const trendTextClass = (trend: Trend) => {
    if (trend === 'up') return 'text-secondary';
    if (trend === 'down') return 'text-error';
    return 'text-on-surface-variant';
};

export function TrendingTickers({
    tickers,
    onSelectTicker,
}: TrendingTickersProps) {
    return (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-10">
            <div className="col-span-full flex items-center justify-between px-2">
                <h2 className="text-xs uppercase tracking-[0.2em] font-bold text-outline tabular-nums">
                    Trending Tickers
                </h2>
                <span className="h-[1px] flex-grow mx-4 bg-outline-variant/30" />
                <button className="text-[10px] text-primary-container hover:underline tracking-widest uppercase">
                    View All
                </button>
            </div>

            {tickers.map((ticker) => (
                <button
                    key={ticker.symbol}
                    type="button"
                    onClick={() => onSelectTicker?.(ticker.symbol)}
                    className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-3 group hover:bg-surface-container transition-colors text-left focus-within:ring-2 focus-within:ring-primary-container outline-none"
                >
                    <div className="flex justify-between items-start">
                        <div>
                            <span className="text-xs font-bold text-outline tracking-wider tabular-nums">
                                {ticker.symbol}
                            </span>
                            <h3 className="text-primary-fixed font-bold">{ticker.name}</h3>
                        </div>
                        {trendIcon(ticker.trend)}
                    </div>
                    <div className="flex items-end justify-between tabular-nums">
                        <span className="text-2xl font-bold tracking-tight">
                            {ticker.price}
                        </span>
                        <span className={`font-medium text-sm ${trendTextClass(ticker.trend)}`}>
                            {ticker.change}
                        </span>
                    </div>
                </button>
            ))}
        </div>
    );
}
