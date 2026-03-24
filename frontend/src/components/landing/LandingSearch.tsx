import { Search } from 'lucide-react';

type LandingSearchProps = {
    ticker: string;
    onTickerChange: (value: string) => void;
    onAnalyze: () => void;
};

export function LandingSearch({
    ticker,
    onTickerChange,
    onAnalyze,
}: LandingSearchProps) {
    const canAnalyze = ticker.trim().length > 0;

    return (
        <div className="relative group">
            <div className="absolute -inset-1 bg-gradient-to-r from-primary-container/20 to-secondary/20 rounded-xl blur-lg opacity-50 group-hover:opacity-100 transition duration-1000 group-hover:duration-200" />
            <div className="relative glass-panel rounded-xl flex items-center p-2 focus-within:ring-2 focus-within:ring-primary-container transition-all">
                <Search className="text-primary-container mx-4" size={18} />
                <input
                    aria-label="Enter Ticker for financial analysis"
                    className="w-full bg-transparent border-none text-lg md:text-xl font-body py-4 outline-none focus:ring-0 placeholder:text-outline/60 text-primary-fixed"
                    placeholder="Enter Ticker (e.g. AAPL, TSLA, NVDA)"
                    type="text"
                    value={ticker}
                    onChange={(event) =>
                        onTickerChange(event.target.value.toUpperCase())
                    }
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && canAnalyze) {
                            onAnalyze();
                        }
                    }}
                />
                <button
                    className="bg-primary-container text-on-primary px-6 md:px-8 py-3 rounded-lg font-bold text-xs md:text-sm tracking-wide hover:brightness-110 active:scale-95 transition-all focus:ring-2 focus:ring-offset-2 focus:ring-primary-container focus:ring-offset-surface disabled:opacity-50"
                    onClick={onAnalyze}
                    disabled={!canAnalyze}
                >
                    ANALYZE
                </button>
            </div>
        </div>
    );
}
