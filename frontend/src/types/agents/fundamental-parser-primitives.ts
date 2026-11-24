import { isRecord } from '../preview';

export type Parser<T> = (value: unknown, context: string) => T;
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };


export function record(value: unknown, context: string): Record<string, unknown> {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
}

export function isContractObject<T extends object>(value: unknown, fields: { [K in keyof T]-?: Parser<T[K]> }, context: string): value is T {
    const input = record(value, context);
    for (const key of Object.keys(input)) {
        if (!Object.hasOwn(fields, key)) throw new TypeError(`${context}.${key} is unsupported.`);
    }
    for (const key in fields) fields[key](input[key], `${context}.${key}`);
    return true;
}

export function object<T extends object>(fields: { [K in keyof T]-?: Parser<T[K]> }): Parser<T> {
    return (value, context) => {
        if (isContractObject(value, fields, context)) return value;
        throw new TypeError(`${context} does not match the contract.`);
    };
}

export const text: Parser<string> = (value, context) => {
    if (typeof value !== 'string') throw new TypeError(`${context} must be a string.`);
    return value;
};
export const nonEmpty: Parser<string> = (value, context) => {
    const parsed = text(value, context);
    if (!parsed.length) throw new TypeError(`${context} must be non-empty.`);
    return parsed;
};
export const boolean: Parser<boolean> = (value, context) => {
    if (typeof value !== 'boolean') throw new TypeError(`${context} must be a boolean.`);
    return value;
};
export const integer: Parser<number> = (value, context) => {
    if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new TypeError(`${context} must be a safe integer.`);
    return value;
};
export const nullValue: Parser<null> = (value, context) => {
    if (value !== null) throw new TypeError(`${context} must be null.`);
    return value;
};
export function optional<T>(parse: Parser<T>): Parser<T | undefined> {
    return (value, context) => value === undefined ? undefined : parse(value, context);
}
export function literal<const T extends string>(...choices: T[]): Parser<T> {
    return (value, context) => {
        const parsed = choices.find((choice) => choice === value);
        if (parsed === undefined) throw new TypeError(`${context} must be ${choices.join(' | ')}.`);
        return parsed;
    };
}
export function union<A, B>(first: Parser<A>, second: Parser<B>): Parser<A | B> {
    return (value, context) => {
        try { return first(value, context); } catch (error) {
            if (!(error instanceof TypeError)) throw error;
        }
        return second(value, context);
    };
}
export function array<T>(parse: Parser<T>): Parser<T[]> {
    return (value, context) => {
        if (!Array.isArray(value)) throw new TypeError(`${context} must be an array.`);
        return value.map((item, index) => parse(item, `${context}[${index}]`));
    };
}
export function dictionary<T>(parse: Parser<T>): Parser<Record<string, T>> {
    return (value, context) => Object.fromEntries(Object.entries(record(value, context)).map(
        ([key, item]) => [key, parse(item, `${context}.${key}`)],
    ));
}
export const json: Parser<JsonValue> = (value, context) => {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (Array.isArray(value)) return array(json)(value, context);
    return dictionary(json)(value, context);
};
export function matching(pattern: RegExp, description: string): Parser<string> {
    return (value, context) => {
        const parsed = text(value, context);
        if (!pattern.test(parsed)) throw new TypeError(`${context} must be ${description}.`);
        return parsed;
    };
}
export const DECIMAL_PATTERN = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;
export const isFundamentalDecimalText = (value: string): boolean => DECIMAL_PATTERN.test(value);
export const decimal = matching(DECIMAL_PATTERN, 'canonical Decimal text');
export const integerText = matching(/^(?:0|-?[1-9][0-9]*)$/, 'canonical integer text');
export const digest = matching(/^[0-9a-f]{64}$/, 'a lowercase SHA-256 digest');
export const date: Parser<string> = (value, context) => {
    const parsed = matching(/^\d{4}-\d{2}-\d{2}$/, 'an ISO date')(value, context);
    const instant = Date.parse(`${parsed}T00:00:00Z`);
    if (!Number.isFinite(instant) || new Date(instant).toISOString().slice(0, 10) !== parsed)
        throw new TypeError(`${context} must be a valid ISO calendar date.`);
    return parsed;
};
export const timestamp: Parser<string> = (value, context) => {
    const parsed = text(value, context);
    if (!/^\d{4}-\d{2}-\d{2}T/.test(parsed) || !Number.isFinite(Date.parse(parsed))) {
        throw new TypeError(`${context} must be an ISO timestamp.`);
    }
    date(parsed.slice(0, 10), context);
    return parsed;
};
