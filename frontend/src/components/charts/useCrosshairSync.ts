import { useCallback, useMemo, useRef, useState } from 'react';
import type { BusinessDay, IRange, Time, UTCTimestamp } from 'lightweight-charts';

export interface CrosshairSyncState {
    activeCrosshairSourceId: string | null;
    activeRangeSourceId: string | null;
    crosshairTime: UTCTimestamp | null;
    crosshairPoint: { x: number; y: number } | null;
    visibleTimeRange: IRange<Time> | null;
    scrollPosition: number | null;
    requestCrosshair: (
        sourceId: string,
        time: UTCTimestamp | null,
        point?: { x: number; y: number } | null
    ) => void;
    requestVisibleTimeRange: (sourceId: string, range: IRange<Time> | null) => void;
    requestScrollPosition: (sourceId: string, position: number | null) => void;
    activateCrosshairSource: (sourceId: string) => void;
    activateRangeSource: (sourceId: string) => void;
    clearCrosshairSource: (sourceId: string) => void;
    clearRangeSource: (sourceId: string) => void;
}

const timeKey = (time: Time | null | undefined) => {
    if (time === null || time === undefined) return 'null';
    if (typeof time === 'number') return `n:${time}`;
    if (typeof time === 'string') return `s:${time}`;
    const businessDay = time as BusinessDay;
    return `b:${businessDay.year}-${businessDay.month}-${businessDay.day}`;
};

const rangeKey = (range: IRange<Time> | null) => {
    if (!range) return 'null';
    return `${timeKey(range.from)}|${timeKey(range.to)}`;
};

export const useCrosshairSync = (): CrosshairSyncState => {
    const [activeCrosshairSourceId, setActiveCrosshairSourceId] = useState<string | null>(null);
    const [activeRangeSourceId, setActiveRangeSourceId] = useState<string | null>(null);
    const [crosshairTime, setCrosshairTime] = useState<UTCTimestamp | null>(null);
    const [crosshairPoint, setCrosshairPoint] = useState<{ x: number; y: number } | null>(null);
    const [visibleTimeRange, setVisibleTimeRange] = useState<IRange<Time> | null>(null);
    const [scrollPosition, setScrollPosition] = useState<number | null>(null);
    const lastCrosshairRef = useRef<{ id: string; time: UTCTimestamp | null; pointKey: string } | null>(null);
    const lastRangeRef = useRef<{ id: string; key: string; range: IRange<Time> | null } | null>(null);
    const lastScrollRef = useRef<{ id: string; position: number | null } | null>(null);
    const activeCrosshairSourceIdRef = useRef<string | null>(null);
    const activeRangeSourceIdRef = useRef<string | null>(null);

    if (activeCrosshairSourceIdRef.current !== activeCrosshairSourceId) {
        activeCrosshairSourceIdRef.current = activeCrosshairSourceId;
    }
    if (activeRangeSourceIdRef.current !== activeRangeSourceId) {
        activeRangeSourceIdRef.current = activeRangeSourceId;
    }

    const requestCrosshair = useCallback(
        (sourceId: string, time: UTCTimestamp | null, point?: { x: number; y: number } | null) => {
            if (activeCrosshairSourceIdRef.current && activeCrosshairSourceIdRef.current !== sourceId) return;
            const resolvedPoint = point ?? null;
            const pointKey = resolvedPoint
                ? `${Math.round(resolvedPoint.x)}:${Math.round(resolvedPoint.y)}`
                : 'null';
            if (
                lastCrosshairRef.current?.id === sourceId &&
                lastCrosshairRef.current?.time === time &&
                lastCrosshairRef.current?.pointKey === pointKey
            ) {
                return;
            }
            activeCrosshairSourceIdRef.current = sourceId;
            lastCrosshairRef.current = { id: sourceId, time, pointKey };
            setActiveCrosshairSourceId(sourceId);
            setCrosshairTime(time);
            setCrosshairPoint(resolvedPoint);
        },
        []
    );

    const requestVisibleTimeRange = useCallback(
        (sourceId: string, range: IRange<Time> | null) => {
            const nextKey = rangeKey(range);
            if (lastRangeRef.current?.id === sourceId && lastRangeRef.current?.key === nextKey) return;
            activeRangeSourceIdRef.current = sourceId;
            lastRangeRef.current = { id: sourceId, key: nextKey, range };
            setActiveRangeSourceId(sourceId);
            setVisibleTimeRange(range);
        },
        []
    );

    const requestScrollPosition = useCallback(
        (sourceId: string, position: number | null) => {
            if (lastScrollRef.current?.id === sourceId && lastScrollRef.current?.position === position) return;
            activeRangeSourceIdRef.current = sourceId;
            lastScrollRef.current = { id: sourceId, position };
            setActiveRangeSourceId(sourceId);
            setScrollPosition(position);
        },
        []
    );

    const activateCrosshairSource = useCallback((sourceId: string) => {
        activeCrosshairSourceIdRef.current = sourceId;
        setActiveCrosshairSourceId(sourceId);
    }, []);

    const activateRangeSource = useCallback((sourceId: string) => {
        activeRangeSourceIdRef.current = sourceId;
        setActiveRangeSourceId(sourceId);
    }, []);

    const clearCrosshairSource = useCallback(
        (sourceId: string) => {
            if (activeCrosshairSourceIdRef.current !== sourceId) return;
            activeCrosshairSourceIdRef.current = null;
            setActiveCrosshairSourceId(null);
            setCrosshairTime(null);
            setCrosshairPoint(null);
        },
        []
    );

    const clearRangeSource = useCallback(
        (sourceId: string) => {
            if (activeRangeSourceIdRef.current !== sourceId) return;
            activeRangeSourceIdRef.current = null;
            setActiveRangeSourceId(null);
            setVisibleTimeRange(null);
            setScrollPosition(null);
        },
        []
    );

    return useMemo(
        () => ({
            activeCrosshairSourceId,
            activeRangeSourceId,
            crosshairTime,
            crosshairPoint,
            visibleTimeRange,
            scrollPosition,
            requestCrosshair,
            requestVisibleTimeRange,
            requestScrollPosition,
            activateCrosshairSource,
            activateRangeSource,
            clearCrosshairSource,
            clearRangeSource,
        }),
        [
            activeCrosshairSourceId,
            activeRangeSourceId,
            crosshairTime,
            crosshairPoint,
            visibleTimeRange,
            scrollPosition,
            requestCrosshair,
            requestVisibleTimeRange,
            requestScrollPosition,
            activateCrosshairSource,
            activateRangeSource,
            clearCrosshairSource,
            clearRangeSource,
        ]
    );
};
