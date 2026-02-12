export interface ExecutorSuccess {
    params: Record<string, unknown>;
    model_type: string;
}

export interface ExecutorError {
    message: string;
}

export type ExecutorResult = ExecutorSuccess | ExecutorError;

export interface AuditorSuccess {
    passed: boolean;
    messages: string[];
}

export interface AuditorError {
    message: string;
}

export type AuditorResult = AuditorSuccess | AuditorError;

export interface CalculatorSuccess {
    metrics: Record<string, unknown>;
    model_type: string;
}

export interface CalculatorError {
    message: string;
}

export type CalculatorResult = CalculatorSuccess | CalculatorError;
