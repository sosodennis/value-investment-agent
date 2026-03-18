export type IndicatorTone = 'positive' | 'neutral' | 'warning' | 'danger';

type IconKey = 'activity' | 'alert' | 'zap' | 'up' | 'down';

export type MacdToneDescriptor = {
    tone: IndicatorTone;
    label: string;
    meaning: string;
    tacticalReadout: string;
};

export type SignalDescriptor = {
    tone: IndicatorTone;
    label: string;
    meaning: string;
    tacticalReadout: string;
};

export type MarketStatusDescriptor = {
    status: string;
    readoutLabel: string;
    readout: string;
    tone: IndicatorTone;
    icon: IconKey;
};

export type QualityStatusDescriptor = {
    tone: IndicatorTone;
    label: string;
    meaning: string;
};

export type IndicatorHighlightDescriptor = {
    displayName: string;
    stateLabel: string | null;
};

type MomentumSummaryInput = {
    macd?: MacdToneDescriptor | null;
    rsi?: SignalDescriptor | null;
    fd?: SignalDescriptor | null;
    rsiValue?: number | null;
    fdValue?: number | null;
};

export const resolveMacdTone = (
    macd: number | null,
    signal: number | null
): MacdToneDescriptor => {
    if (macd === null || Number.isNaN(macd)) {
        return {
            tone: 'neutral',
            label: 'No Data',
            meaning: 'MACD data is unavailable for this timeframe.',
            tacticalReadout: 'Wait for Data',
        };
    }
    if (signal === null || Number.isNaN(signal)) {
        return {
            tone: 'neutral',
            label: 'No Signal Line',
            meaning: 'MACD is available, but its signal line is missing, so momentum alignment is unclear.',
            tacticalReadout: 'Use Caution',
        };
    }
    if (macd > signal && macd > 0) {
        return {
            tone: 'positive',
            label: 'Bullish Above Zero',
            meaning: 'MACD is above its signal line and above zero, which points to stronger bullish momentum.',
            tacticalReadout: 'Momentum Confirmed',
        };
    }
    if (macd < signal && macd < 0) {
        return {
            tone: 'danger',
            label: 'Bearish Below Zero',
            meaning: 'MACD is below its signal line and below zero, which points to persistent downside momentum.',
            tacticalReadout: 'Downtrend Risk Active',
        };
    }
    if (macd > signal) {
        return {
            tone: 'warning',
            label: 'Above Signal',
            meaning: 'Momentum is improving versus the signal line, but the broader backdrop is still below zero.',
            tacticalReadout: 'Early Improvement, Avoid Chasing',
        };
    }
    if (macd < signal) {
        return {
            tone: 'warning',
            label: 'Below Signal',
            meaning: 'Momentum is weakening versus the signal line, even though the broader backdrop is not fully broken.',
            tacticalReadout: 'Wait for Better Alignment',
        };
    }
    return {
        tone: 'neutral',
        label: 'Flat',
        meaning: 'MACD and the signal line are nearly aligned, so momentum is not giving a strong edge.',
        tacticalReadout: 'Wait & Observe',
    };
};

export const getMarketStatusDescriptor = (
    zScore: number
): MarketStatusDescriptor => {
    if (zScore > 2.0) {
        return {
            status: 'Extreme Overheating',
            readoutLabel: 'Tactical Readout',
            readout: 'Do Not Chase',
            tone: 'danger',
            icon: 'alert',
        };
    }
    if (zScore < -2.0) {
        return {
            status: 'Extreme Fear / Panic',
            readoutLabel: 'Tactical Readout',
            readout: 'Potential Rebound Zone',
            tone: 'positive',
            icon: 'zap',
        };
    }
    if (Math.abs(zScore) > 1.0) {
        const isBullish = zScore > 0;
        return {
            status: isBullish ? 'Bullish Momentum Building' : 'Bearish Undercurrents',
            readoutLabel: 'Tactical Readout',
            readout: 'Trend is Active - Monitor Closely',
            tone: 'warning',
            icon: isBullish ? 'up' : 'down',
        };
    }
    return {
        status: 'Market Equilibrium',
        readoutLabel: 'Tactical Readout',
        readout: 'Wait & Observe',
        tone: 'neutral',
        icon: 'activity',
    };
};

export const resolveRsiDescriptor = (
    value: number | null,
    explicitState?: string | null
): SignalDescriptor => {
    const normalizedState = _normalizeState(explicitState);
    if (value === null || Number.isNaN(value)) {
        return {
            tone: 'neutral',
            label: 'No Data',
            meaning: 'RSI data is unavailable for this timeframe.',
            tacticalReadout: 'Wait for Data',
        };
    }
    if (normalizedState === 'OVERBOUGHT' || value >= 70) {
        return {
            tone: 'danger',
            label: 'Overbought',
            meaning: 'Price has moved hot enough that short-term upside may be stretched.',
            tacticalReadout: 'Do Not Chase Strength',
        };
    }
    if (normalizedState === 'OVERSOLD' || value <= 30) {
        return {
            tone: 'positive',
            label: 'Oversold',
            meaning: 'Selling pressure looks stretched, so rebound risk is rising.',
            tacticalReadout: 'Watch for Rebound',
        };
    }
    if (normalizedState === 'BULLISH_BIAS' || value >= 55) {
        return {
            tone: 'warning',
            label: 'Bullish Bias',
            meaning: 'Momentum is leaning upward, but it is not yet in an extreme zone.',
            tacticalReadout: 'Trend Bias Up',
        };
    }
    if (normalizedState === 'BEARISH_BIAS' || value <= 45) {
        return {
            tone: 'warning',
            label: 'Bearish Bias',
            meaning: 'Momentum still leans weak, even though selling is not yet fully stretched.',
            tacticalReadout: 'Momentum Still Soft',
        };
    }
    return {
        tone: 'neutral',
        label: 'Neutral Range',
        meaning: 'Momentum is balanced enough that RSI is not showing a strong edge.',
        tacticalReadout: 'Wait & Observe',
    };
};

export const resolveFdDescriptor = (
    value: number | null,
    explicitState?: string | null
): SignalDescriptor => {
    const normalizedState = _normalizeState(explicitState);
    if (value === null || Number.isNaN(value)) {
        return {
            tone: 'neutral',
            label: 'No Data',
            meaning: 'FD Z-score data is unavailable for this timeframe.',
            tacticalReadout: 'Wait for Data',
        };
    }
    if (value >= 2 || (normalizedState === 'EXTREME' && value >= 0)) {
        return {
            tone: 'danger',
            label: 'Upside Stretch',
            meaning: 'Price action sits well above its normal statistical range.',
            tacticalReadout: 'Do Not Chase',
        };
    }
    if (value <= -2 || (normalizedState === 'EXTREME' && value < 0)) {
        return {
            tone: 'danger',
            label: 'Downside Stretch',
            meaning: 'Price action sits well below its normal statistical range.',
            tacticalReadout: 'Potential Rebound Zone',
        };
    }
    if (value >= 1 || (normalizedState === 'ELEVATED' && value >= 0)) {
        return {
            tone: 'warning',
            label: 'Elevated Upside Deviation',
            meaning: 'Price is running above normal, but not yet at a full statistical extreme.',
            tacticalReadout: 'Monitor for Cooling',
        };
    }
    if (value <= -1 || (normalizedState === 'ELEVATED' && value < 0)) {
        return {
            tone: 'warning',
            label: 'Elevated Downside Deviation',
            meaning: 'Price is running below normal, but not yet at a full statistical extreme.',
            tacticalReadout: 'Monitor for Stabilization',
        };
    }
    return {
        tone: 'neutral',
        label: 'Near Normal',
        meaning: 'The statistical reading is close to its usual range.',
        tacticalReadout: 'Wait & Observe',
    };
};

export const buildMomentumSummaryLine = ({
    macd,
    rsi,
    fd,
    rsiValue,
    fdValue,
}: MomentumSummaryInput): string | null => {
    const parts: string[] = [];
    if (macd && macd.label !== 'No Data') {
        parts.push(`MACD is ${macd.label.toLowerCase()}`);
    }
    if (fd && fdValue !== null && fdValue !== undefined && fd.label !== 'No Data') {
        parts.push(`FD Z-score is ${fd.label.toLowerCase()} (${fdValue.toFixed(3)})`);
    }
    if (rsi && rsiValue !== null && rsiValue !== undefined && rsi.label !== 'No Data') {
        parts.push(`RSI is in ${rsi.label.toLowerCase()} (${rsiValue.toFixed(3)})`);
    }
    return parts.length > 0 ? parts.join(' · ') : null;
};

export const describeIndicatorHighlight = (
    name: string,
    state?: string | null
): IndicatorHighlightDescriptor => {
    const displayName = _INDICATOR_DISPLAY_NAMES[name] ?? _humanizeSignalName(name);
    const normalizedState = typeof state === 'string' ? state.trim().toUpperCase() : '';
    const perIndicatorStateMap = _INDICATOR_STATE_LABELS[name];
    if (perIndicatorStateMap && normalizedState in perIndicatorStateMap) {
        return {
            displayName,
            stateLabel: perIndicatorStateMap[normalizedState] ?? null,
        };
    }
    return {
        displayName,
        stateLabel: normalizedState ? _humanizeSignalName(normalizedState) : null,
    };
};

export const getQualityStatusDescriptor = (
    isDegraded?: boolean | null,
    overallQuality?: string | null
): QualityStatusDescriptor => {
    const normalizedQuality = _normalizeState(overallQuality);
    if (isDegraded) {
        return {
            tone: 'warning',
            label: 'Partial Coverage',
            meaning: 'Some upstream inputs were missing or downgraded, so read the setup with extra caution.',
        };
    }
    if (normalizedQuality === 'HIGH') {
        return {
            tone: 'positive',
            label: 'High Coverage',
            meaning: 'Core evidence inputs are present and the technical readout is well-supported.',
        };
    }
    if (normalizedQuality === 'MEDIUM') {
        return {
            tone: 'warning',
            label: 'Usable Coverage',
            meaning: 'The technical readout is usable, but some secondary evidence is thinner than ideal.',
        };
    }
    if (normalizedQuality === 'LOW') {
        return {
            tone: 'danger',
            label: 'Thin Coverage',
            meaning: 'Only a limited evidence set is available, so conviction should stay restrained.',
        };
    }
    return {
        tone: 'neutral',
        label: 'Coverage Unrated',
        meaning: 'Coverage metadata is not available for this run.',
    };
};

export const formatAlertLifecycleLabel = (state?: string | null): string => {
    const normalized = _normalizeState(state);
    if (!normalized) return 'Unknown Lifecycle';
    if (normalized === 'ACTIVE') return 'Active';
    if (normalized === 'MONITORING') return 'Monitoring';
    if (normalized === 'SUPPRESSED') return 'Suppressed';
    return _humanizeSignalName(normalized);
};

export const formatAlertQualityGateLabel = (gate?: string | null): string => {
    const normalized = _normalizeState(gate);
    if (!normalized) return 'Unknown Gate';
    if (normalized === 'PASSED') return 'Passed';
    if (normalized === 'DEGRADED') return 'Degraded';
    if (normalized === 'FAILED') return 'Failed';
    return _humanizeSignalName(normalized);
};

const _INDICATOR_DISPLAY_NAMES: Record<string, string> = {
    ADX_14: 'Trend Strength',
    ATRP_14: 'Relative Volatility',
    ATR_14: 'Average Move Size',
    BB_BANDWIDTH_20: 'Volatility Compression',
    FD_Z_SCORE: 'FD Z-Score',
    FD_OPTIMAL_D: 'Series Memory',
    FD_ADF_STAT: 'Stability Check',
};

const _INDICATOR_STATE_LABELS: Record<string, Record<string, string | null>> = {
    ADX_14: {
        NEUTRAL: 'Trend Not Strong',
    },
    ATRP_14: {
        NEUTRAL: 'Normal Range',
    },
    ATR_14: {
        NEUTRAL: 'Typical Move Size',
    },
    FD_Z_SCORE: {
        NEUTRAL: 'Near Normal',
    },
    FD_OPTIMAL_D: {
        NEUTRAL: 'Persistent Structure',
    },
    FD_ADF_STAT: {
        NEUTRAL: 'Stable Signal',
    },
};

const _normalizeState = (value?: string | null): string => {
    if (typeof value !== 'string') {
        return '';
    }
    return value.trim().toUpperCase();
};

const _humanizeSignalName = (value: string): string =>
    value
        .split('_')
        .map((part) =>
            part ? `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}` : ''
        )
        .join(' ')
        .trim();
