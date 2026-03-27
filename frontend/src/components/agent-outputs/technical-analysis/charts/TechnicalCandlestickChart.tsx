import React, { useEffect, useMemo, useRef } from 'react';
import {
    CandlestickSeries,
    ColorType,
    createChart,
    CrosshairMode,
    HistogramSeries,
    IChartApi,
    ISeriesApi,
    IRange,
    BusinessDay,
    LineSeries,
    LineStyle,
    MouseEventParams,
    Time,
    UTCTimestamp,
} from 'lightweight-charts';
import { CrosshairSyncState } from './useCrosshairSync';

export interface CandlestickDatum {
    time: UTCTimestamp;
    open: number;
    high: number;
    low: number;
    close: number;
}

export interface VolumeDatum {
    time: UTCTimestamp;
    value: number;
    color?: string;
}

export interface OverlayLineSeries {
    id: string;
    data: { time: UTCTimestamp; value: number }[];
    color: string;
    lineWidth?: 1 | 2 | 3 | 4;
    lineStyle?: 'solid' | 'dashed';
}

interface TechnicalCandlestickChartProps {
    candles: CandlestickDatum[];
    volumes: VolumeDatum[];
    overlays?: OverlayLineSeries[];
    height?: number;
    showTime?: boolean;
    showTimeScale?: boolean;
    showVolume?: boolean;
    syncId: string;
    syncState: CrosshairSyncState;
}

const DEFAULT_HEIGHT = 320;
type VisibleTimeRange = IRange<Time>;

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

const isBusinessDay = (time: Time): time is BusinessDay => {
    if (!isRecord(time)) return false;
    return (
        typeof time.year === 'number' &&
        typeof time.month === 'number' &&
        typeof time.day === 'number'
    );
};

const isUtcTimestamp = (value: number): value is UTCTimestamp => Number.isFinite(value);

const normalizeTime = (time: Time): UTCTimestamp | null => {
    if (typeof time === 'number') return isUtcTimestamp(time) ? time : null;
    if (typeof time === 'string') {
        const parsed = Date.parse(time);
        if (Number.isNaN(parsed)) return null;
        const seconds = Math.floor(parsed / 1000);
        return isUtcTimestamp(seconds) ? seconds : null;
    }
    if (isBusinessDay(time)) {
        const utc = Date.UTC(time.year, time.month - 1, time.day);
        const seconds = Math.floor(utc / 1000);
        return isUtcTimestamp(seconds) ? seconds : null;
    }
    return null;
};

const findNearestTime = (times: UTCTimestamp[], target: UTCTimestamp): UTCTimestamp | null => {
    if (times.length === 0) return null;
    const first = times[0];
    const last = times[times.length - 1];
    if (target <= first) return first;
    if (target >= last) return last;
    let low = 0;
    let high = times.length - 1;
    while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const value = times[mid];
        if (value === target) return value;
        if (value < target) {
            low = mid + 1;
        } else {
            high = mid - 1;
        }
    }
    const left = times[Math.max(0, high)];
    const right = times[Math.min(times.length - 1, low)];
    return target - left <= right - target ? left : right;
};

export const TechnicalCandlestickChart: React.FC<TechnicalCandlestickChartProps> = ({
    candles,
    volumes,
    overlays = [],
    height = DEFAULT_HEIGHT,
    showTime = false,
    showTimeScale = true,
    showVolume = true,
    syncId,
    syncState,
}) => {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
    const overlaySeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
    const isSyncingRef = useRef(false);
    const lastEmittedRef = useRef<{ time: UTCTimestamp | null; pointKey: string } | null>(null);
    const pendingTimeRef = useRef<UTCTimestamp | null>(null);
    const pendingPointRef = useRef<{ x: number; y: number } | null>(null);
    const rafRef = useRef<number | null>(null);
    const rangeSyncGateRef = useRef(0);
    const activeCrosshairSourceIdRef = useRef<string | null>(syncState.activeCrosshairSourceId);
    const hasDataRef = useRef(false);
    const {
        requestCrosshair,
        requestVisibleTimeRange,
        activateCrosshairSource,
        clearCrosshairSource,
    } = syncState;

    const hasData = useMemo(() => candles.length > 0, [candles]);
    const priceByTime = useMemo(() => {
        const map = new Map<UTCTimestamp, number>();
        candles.forEach((candle) => {
            map.set(candle.time, candle.close);
        });
        return map;
    }, [candles]);
    const sortedTimes = useMemo(() => candles.map((candle) => candle.time).sort((a, b) => a - b), [candles]);

    useEffect(() => {
        activeCrosshairSourceIdRef.current = syncState.activeCrosshairSourceId;
    }, [syncState.activeCrosshairSourceId]);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return undefined;

        const chart = createChart(container, {
            width: container.clientWidth,
            height,
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: '#94a3b8',
                fontSize: 11,
                fontFamily: 'ui-sans-serif, system-ui, -apple-system, sans-serif',
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: 'rgba(30, 41, 59, 0.6)' },
                horzLines: { color: 'rgba(30, 41, 59, 0.6)' },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: 'rgba(51, 65, 85, 0.7)',
            },
            timeScale: {
                borderColor: 'rgba(51, 65, 85, 0.7)',
                rightOffset: 0,
                barSpacing: 6,
                fixLeftEdge: true,
                fixRightEdge: true,
                lockVisibleTimeRangeOnResize: true,
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
            },
            handleScale: {
                mouseWheel: true,
                pinch: true,
                axisPressedMouseMove: true,
            },
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#22c55e',
            downColor: '#f87171',
            wickUpColor: '#22c55e',
            wickDownColor: '#f87171',
            borderVisible: false,
        });

        const volumeSeries = showVolume
            ? chart.addSeries(HistogramSeries, {
                  color: 'rgba(148, 163, 184, 0.45)',
                  priceScaleId: '',
                  priceFormat: { type: 'volume' },
              })
            : null;
        if (volumeSeries) {
            volumeSeries.priceScale().applyOptions({
                scaleMargins: { top: 0.8, bottom: 0 },
            });
        }

        chartRef.current = chart;
        candleSeriesRef.current = candleSeries;
        volumeSeriesRef.current = volumeSeries;
        overlaySeriesRef.current = [];

        const handleResize = () => {
            chart.applyOptions({ width: container.clientWidth });
        };

        const resizeObserver = new ResizeObserver(handleResize);
        resizeObserver.observe(container);

        const handleCrosshairMove = (param: MouseEventParams) => {
            // tooltip sync: forward crosshair point to shared state.
            if (isSyncingRef.current) {
                isSyncingRef.current = false;
                return;
            }
            if (!param || !param.time || !param.seriesData || !candleSeriesRef.current || !param.point) {
                return;
            }
            if (!param.seriesData.get(candleSeriesRef.current)) {
                return;
            }
            const normalized = normalizeTime(param.time);
            if (normalized === null) {
                return;
            }
            const bounds = containerRef.current?.getBoundingClientRect();
            if (!bounds) return;
            const point = {
                x: bounds.left + param.point.x,
                y: bounds.top + param.point.y,
            };
            if (activeCrosshairSourceIdRef.current && activeCrosshairSourceIdRef.current !== syncId) {
                return;
            }
            pendingTimeRef.current = normalized;
            pendingPointRef.current = point;
            if (rafRef.current !== null) {
                return;
            }
            rafRef.current = window.requestAnimationFrame(() => {
                rafRef.current = null;
                const next = pendingTimeRef.current;
                if (next === null) return;
                const nextPoint = pendingPointRef.current;
                const pointKey = nextPoint
                    ? `${Math.round(nextPoint.x)}:${Math.round(nextPoint.y)}`
                    : 'null';
                if (lastEmittedRef.current?.time === next && lastEmittedRef.current?.pointKey === pointKey) {
                    return;
                }
                lastEmittedRef.current = { time: next, pointKey };
                requestCrosshair(syncId, next, nextPoint);
            });
        };

        chart.subscribeCrosshairMove(handleCrosshairMove);
        const handleMouseEnter = () => {
            activateCrosshairSource(syncId);
        };
        const handleMouseLeave = () => {
            clearCrosshairSource(syncId);
            if (rafRef.current !== null) {
                window.cancelAnimationFrame(rafRef.current);
                rafRef.current = null;
            }
            pendingTimeRef.current = null;
            pendingPointRef.current = null;
            lastEmittedRef.current = null;
        };
        container.addEventListener('mouseenter', handleMouseEnter);
        container.addEventListener('mouseleave', handleMouseLeave);

        const handleVisibleRangeChange = (range: VisibleTimeRange | null) => {
            if (rangeSyncGateRef.current > 0) {
                rangeSyncGateRef.current -= 1;
                return;
            }
            if (!range) return;
            requestVisibleTimeRange(syncId, range);
        };
        chart.timeScale().subscribeVisibleTimeRangeChange(handleVisibleRangeChange);

        return () => {
            resizeObserver.disconnect();
            chart.unsubscribeCrosshairMove(handleCrosshairMove);
            chart.timeScale().unsubscribeVisibleTimeRangeChange(handleVisibleRangeChange);
            container.removeEventListener('mouseenter', handleMouseEnter);
            container.removeEventListener('mouseleave', handleMouseLeave);
            if (rafRef.current !== null) {
                window.cancelAnimationFrame(rafRef.current);
            }
            chart.remove();
            chartRef.current = null;
            candleSeriesRef.current = null;
            volumeSeriesRef.current = null;
            overlaySeriesRef.current = [];
        };
    }, [
        activateCrosshairSource,
        clearCrosshairSource,
        height,
        requestCrosshair,
        requestVisibleTimeRange,
        showVolume,
        syncId,
    ]);

    useEffect(() => {
        if (!chartRef.current || !candleSeriesRef.current) return;
        candleSeriesRef.current.setData(candles);
        if (volumeSeriesRef.current) {
            volumeSeriesRef.current.setData(volumes);
        }
        if (candles.length > 0 && !hasDataRef.current) {
            chartRef.current.timeScale().fitContent();
            hasDataRef.current = true;
        } else if (candles.length === 0) {
            hasDataRef.current = false;
        }
    }, [candles, volumes]);

    useEffect(() => {
        if (!chartRef.current) return;
        const chart = chartRef.current;
        overlaySeriesRef.current.forEach((series) => chart.removeSeries(series));
        overlaySeriesRef.current = overlays.map((overlay) =>
            chart.addSeries(LineSeries, {
                color: overlay.color,
                lineWidth: overlay.lineWidth ?? 1,
                lineStyle: overlay.lineStyle === 'dashed' ? LineStyle.Dashed : LineStyle.Solid,
                priceLineVisible: false,
                lastValueVisible: false,
            })
        );
        overlaySeriesRef.current.forEach((series, index) => {
            series.setData(overlays[index]?.data ?? []);
        });
    }, [overlays]);

    useEffect(() => {
        if (!chartRef.current) return;
        chartRef.current.applyOptions({
            timeScale: {
                visible: showTimeScale,
                timeVisible: showTime,
                secondsVisible: showTime,
            },
        });
    }, [showTime, showTimeScale]);

    useEffect(() => {
        if (!chartRef.current || !candleSeriesRef.current) return;
        if (syncState.activeCrosshairSourceId === syncId) return;
        if (!syncState.crosshairTime) {
            isSyncingRef.current = true;
            chartRef.current.clearCrosshairPosition();
            return;
        }
        const snapped = findNearestTime(sortedTimes, syncState.crosshairTime);
        if (snapped === null) return;
        const price = priceByTime.get(snapped);
        if (price === undefined) return;
        isSyncingRef.current = true;
        chartRef.current.setCrosshairPosition(price, snapped, candleSeriesRef.current);
    }, [priceByTime, sortedTimes, syncId, syncState.activeCrosshairSourceId, syncState.crosshairTime]);

    useEffect(() => {
        if (!chartRef.current) return;
        if (syncState.activeRangeSourceId === syncId) return;
        if (!syncState.visibleTimeRange) return;
        rangeSyncGateRef.current = 1;
        chartRef.current.timeScale().setVisibleRange(syncState.visibleTimeRange);
    }, [syncId, syncState.activeRangeSourceId, syncState.visibleTimeRange]);

    return (
        <div className="w-full">
            <div
                ref={containerRef}
                className="w-full"
                style={{ height }}
            />
            {!hasData && (
                <div className="mt-3 text-xs text-outline">
                    OHLC data unavailable for this timeframe.
                </div>
            )}
        </div>
    );
};
