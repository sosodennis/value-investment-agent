export interface ExecutorSuccess {
    kind: 'success';
    params: Record<string, any>;
    model_type: string;
}

export interface ExecutorError {
    kind: 'error';
    message: string;
}

export type ExecutorResult = ExecutorSuccess | ExecutorError;

export interface AuditorSuccess {
    kind: 'success';
    passed: boolean;
    messages: string[];
}

export interface AuditorError {
    kind: 'error';
    message: string;
}

export type AuditorResult = AuditorSuccess | AuditorError;

export interface CalculatorSuccess {
    kind: 'success';
    metrics: Record<string, any>;
    model_type: string;
}

export interface CalculatorError {
    kind: 'error';
    message: string;
}

export type CalculatorResult = CalculatorSuccess | CalculatorError;
