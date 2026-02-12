import React, { useMemo } from 'react';
import Form from '@rjsf/core';
import { RJSFSchema, UiSchema, WidgetProps } from '@rjsf/utils';
import validator from '@rjsf/validator-ajv8';
import { Zap, AlertTriangle } from 'lucide-react';
import {
    InterruptResumePayload,
    parseInterruptResumePayload,
} from '@/types/interrupts';

interface EnumOption {
    value: string;
    label?: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

interface DynamicInterruptFormProps {
    schema: RJSFSchema;
    uiSchema?: UiSchema;
    formData?: Record<string, unknown>;
    onSubmit: (data: InterruptResumePayload) => void;
    title?: string;
    description?: string;
}

/**
 * Custom Radio Widget for Ticker Selection
 * Renders options as premium cards instead of standard radio buttons.
 * Style: Compact / Dense for professional look.
 */
const TickerCardRadioWidget = (props: WidgetProps) => {
    const { options, value, onChange, schema } = props;
    const { enumOptions } = options;

    // Fallback logic: RJSF sometimes fails to populate enumOptions in custom widgets
    const finalEnumOptions = useMemo(() => {
        const opts: EnumOption[] = [];
        if (Array.isArray(enumOptions)) {
            enumOptions.forEach((option) => {
                if (
                    option &&
                    typeof option === 'object' &&
                    'value' in option &&
                    typeof option.value === 'string'
                ) {
                    opts.push({
                        value: option.value,
                        label: typeof option.label === 'string' ? option.label : undefined,
                    });
                }
            });
        }
        if (opts.length === 0 && schema.enum) {
            const labelsByValue = new Map<string, string>();
            if (Array.isArray(schema.oneOf)) {
                schema.oneOf.forEach((entry) => {
                    if (!isRecord(entry)) return;
                    const optionValue = entry.const;
                    const optionLabel = entry.title;
                    if (
                        typeof optionValue === 'string' &&
                        typeof optionLabel === 'string'
                    ) {
                        labelsByValue.set(optionValue, optionLabel);
                    }
                });
            }
            const enumValues = schema.enum.filter(
                (entry): entry is string => typeof entry === 'string'
            );
            return enumValues.map((entry) => ({
                value: entry,
                label: labelsByValue.get(entry) ?? entry,
            }));
        }
        return opts;
    }, [enumOptions, schema]);

    return (
        <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3">
                {finalEnumOptions.map((option) => {
                    const isSelected = value === option.value;
                    const fullLabel = option.label ?? option.value;

                    // Safe Parsing: "SYMBOL - NAME (CONFIDENCE% match)"
                    // Handles scenarios where " - " might be missing or formatting is slightly off
                    const parts = fullLabel.split(' - ');
                    const symbol = parts[0] || 'Unknown';
                    const rest = parts.length > 1 ? parts.slice(1).join(' - ') : '';

                    const matchIdx = rest.lastIndexOf(' (');
                    const name = matchIdx !== -1 ? rest.substring(0, matchIdx) : rest || symbol;
                    const matchStr = matchIdx !== -1
                        ? rest.substring(matchIdx + 2).replace(')', '').trim()
                        : '';

                    return (
                        <div
                            key={option.value}
                            onClick={() => onChange(option.value)}
                            className={`
                                relative px-3 py-2.5 rounded-lg border transition-all cursor-pointer group flex justify-between items-center
                                ${isSelected
                                    ? 'bg-slate-900 border-slate-700 shadow-[0_0_15px_rgba(var(--primary-rgb),0.05)]'
                                    : 'bg-slate-950/40 border-slate-900/30 hover:bg-slate-900/40 hover:border-slate-800'}
                            `}
                        >
                            <div className="flex flex-col gap-0.5">
                                <span className={`text-sm font-bold leading-none tracking-tight ${isSelected ? 'text-white' : 'text-slate-200'}`}>
                                    {symbol}
                                </span>
                                <span className="text-[9px] text-slate-500 font-bold uppercase tracking-widest">
                                    {name}
                                </span>
                            </div>

                            <div className="flex items-center gap-6">
                                {matchStr && (
                                    <div className="bg-slate-900/60 px-2 py-0.5 rounded border border-slate-900">
                                        <span className="text-[8px] font-mono font-bold text-slate-600 tracking-tight whitespace-nowrap">
                                            {matchStr.includes('Match') ? matchStr.toUpperCase() : `${matchStr.toUpperCase()} MATCH`}
                                        </span>
                                    </div>
                                )}

                                <div className={`
                                    w-4 h-4 rounded-full border flex items-center justify-center transition-all bg-slate-950/60
                                    ${isSelected ? 'border-primary bg-primary/10 shadow-[0_0_8px_rgba(var(--primary-rgb),0.2)]' : 'border-slate-800 bg-transparent group-hover:border-slate-700'}
                                `}>
                                    {isSelected && (
                                        <div className="w-1.5 h-1.5 bg-primary rounded-full shadow-[0_0_10px_rgba(var(--primary-rgb),1)]" />
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// Register custom widgets
const widgets = {
    RadioWidget: TickerCardRadioWidget,
};

export const DynamicInterruptForm: React.FC<DynamicInterruptFormProps> = ({
    schema,
    uiSchema,
    formData,
    onSubmit,
    title,
    description
}) => {
    // 1. Determine form type
    const isTickerForm = useMemo(() =>
        title?.toLowerCase().includes('ticker') ||
        schema.title?.toLowerCase().includes('ticker'),
        [title, schema.title]);

    // 2. Memoize UI Schema to prevent unnecessary Form re-renders
    const combinedUiSchema = useMemo(() => ({
        ...uiSchema,
        "ui:submitButtonOptions": {
            "props": {
                "className": "w-full mt-3 bg-cyan-600 hover:bg-cyan-500 text-white text-[10px] font-bold py-2.5 rounded-lg transition-all uppercase tracking-[0.15em] shadow-xl shadow-cyan-500/10 border-none cursor-pointer flex items-center justify-center gap-2"
            },
            "submitText": isTickerForm ? "Confirm Selection" : "Submit Decision"
        }
    }), [uiSchema, isTickerForm]);

    return (
        <div className={`
            border rounded-xl overflow-hidden backdrop-blur-xl animate-in fade-in zoom-in-95 duration-500 shadow-xl
            ${isTickerForm
                ? 'bg-amber-500/[0.025] border-amber-500/20 shadow-amber-500/[0.01]'
                : 'bg-slate-950/20 border-slate-900'}
        `}>
            {/* Header section */}
            <div className={`px-4 py-3 flex items-center gap-3 border-b ${isTickerForm ? 'border-amber-500/10' : 'border-slate-800/50'}`}>
                <div className={`p-1.5 rounded-md shrink-0 ${isTickerForm ? 'bg-amber-500/10 shadow-[0_0_10px_rgba(245,158,11,0.05)]' : 'bg-cyan-500/10'}`}>
                    {isTickerForm ? (
                        <Zap size={14} className="text-amber-500" />
                    ) : (
                        <AlertTriangle size={14} className="text-cyan-400" />
                    )}
                </div>
                <div>
                    <h3 className={`text-[10px] font-bold uppercase tracking-[0.2em] ${isTickerForm ? 'text-amber-500' : 'text-white'}`}>
                        {isTickerForm ? 'Ticker Resolution Required' : (title || schema.title || 'Action Required')}
                    </h3>
                    {(description || schema.description) && (
                        <p className="text-[9px] text-slate-500 font-bold mt-0.5 uppercase tracking-tight opacity-80">
                            {description || schema.description || 'Please complete the requested action to proceed.'}
                        </p>
                    )}
                </div>
            </div>

            <div className="p-4">
                <div className="interrupt-form-container">
                    <Form
                        schema={schema}
                        uiSchema={combinedUiSchema}
                        formData={formData}
                        widgets={widgets}
                        validator={validator}
                        onSubmit={({ formData: data }) => {
                            const payload = parseInterruptResumePayload(data);
                            onSubmit(payload);
                        }}
                        className="space-y-4"
                    />
                </div>
            </div>

            <style jsx global>{`
                .interrupt-form-container .form-group {
                    margin-bottom: 0px;
                }
                .interrupt-form-container .field-object > label,
                .interrupt-form-container .field-string > label {
                    display: none;
                }
                .interrupt-form-container fieldset {
                    border: none;
                    padding: 0;
                    margin: 0;
                }
                .interrupt-form-container legend {
                    display: none;
                }
                .interrupt-form-container label {
                    display: block;
                    font-size: 10px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.1em;
                    color: #64748b; /* slate-500 */
                    margin-bottom: 0.5rem;
                }
                .interrupt-form-container input[type="text"],
                .interrupt-form-container textarea,
                .interrupt-form-container select {
                    width: 100%;
                    background: rgba(15, 23, 42, 0.6);
                    border: 1px solid #1e293b;
                    border-radius: 0.5rem;
                    padding: 0.625rem 0.75rem;
                    color: white;
                    font-size: 0.875rem;
                    transition: all 0.2s;
                    box-sizing: border-box;
                }
                .interrupt-form-container input:focus,
                .interrupt-form-container textarea:focus,
                .interrupt-form-container select:focus {
                    outline: none;
                    border-color: #06b6d4; /* cyan-500 */
                    background: rgba(15, 23, 42, 0.9);
                    box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.05);
                }
                .interrupt-form-container .field-description {
                    font-size: 10px;
                    color: #475569; /* slate-600 */
                    margin-top: 0.5rem;
                    font-weight: 500;
                }
                .interrupt-form-container .error-detail {
                    color: #f43f5e; /* rose-500 */
                    font-size: 10px;
                    font-weight: 600;
                    margin-top: 0.5rem;
                    background: rgba(244, 63, 94, 0.05);
                    padding: 0.5rem 1rem;
                    border-radius: 0.5rem;
                    list-style: none;
                }
            `}</style>
        </div>
    );
};
