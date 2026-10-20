type LogFields = Record<string, unknown>;
type LogLevel = 'debug' | 'error';

type ClientLogRecord = {
    timestamp: string;
    level: Uppercase<LogLevel>;
    service: 'frontend';
    environment: string;
    logger: 'frontend';
    message: string;
    event: string;
    fields?: LogFields;
};

const REDACTED = '[REDACTED]';
const SENSITIVE_KEY = /(authorization|cookie|password|token|secret|api[_-]?key)/i;

const redactFields = (fields: LogFields): LogFields =>
    Object.fromEntries(
        Object.entries(fields).map(([key, value]) => [
            key,
            SENSITIVE_KEY.test(key) ? REDACTED : value,
        ])
    );

const writeLog = (level: LogLevel, event: string, fields?: LogFields): void => {
    const record: ClientLogRecord = {
        timestamp: new Date().toISOString(),
        level: level === 'error' ? 'ERROR' : 'DEBUG',
        service: 'frontend',
        environment: process.env.NODE_ENV ?? 'development',
        logger: 'frontend',
        message: event,
        event,
    };
    if (fields) record.fields = redactFields(fields);

    const output = JSON.stringify(record);
    if (level === 'error') {
        console.error(output);
    } else {
        console.debug(output);
    }
};

export const clientLogger = {
    debug: (event: string, fields?: LogFields): void => {
        if (process.env.NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_LOGS === 'true') {
            writeLog('debug', event, fields);
        }
    },
    error: (event: string, fields?: LogFields): void => {
        writeLog('error', event, fields);
    },
};
