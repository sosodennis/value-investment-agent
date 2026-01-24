import React from 'react';
import Form from '@rjsf/core';
import { RJSFSchema, UiSchema, WidgetProps } from '@rjsf/utils';
import validator from '@rjsf/validator-ajv8';
import { Zap, AlertTriangle, CheckCircle } from 'lucide-react';

interface DynamicInterruptFormProps {
    schema: RJSFSchema;
    uiSchema?: UiSchema;
    formData?: any;
    onSubmit: (data: any) => void;
    title?: string;
    description?: string;
}

/**
 * Custom Radio Widget for Ticker Selection
 * Renders options as premium cards instead of standard radio buttons.
 */
const TickerCardRadioWidget = (props: WidgetProps) => {
    const { options, value, onChange } = props;
    const { enumOptions, enumNames } = options;

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4">
                {(enumOptions as any[]).map((option, index) => {
                    const isSelected = value === option.value;
                    const fullLabel = enumNames ? enumNames[index] : option.label;

                    // Parse: "SYMBOL - NAME (CONFIDENCE% match)"
                    const parts = fullLabel.split(' - ');
                    const symbol = parts[0];
                    const rest = parts[1] || '';
                    const matchIdx = rest.lastIndexOf(' (');
                    const name = matchIdx !== -1 ? rest.substring(0, matchIdx) : rest;
                    const matchStr = matchIdx !== -1 ? rest.substring(matchIdx + 2).replace(')', '') : '';

                    return (
                        <div
                            key={option.value}
                            onClick={() => onChange(option.value)}
                            className={`
                                relative p-4 rounded-xl border-2 transition-all cursor-pointer group flex justify-between items-center
                                ${isSelected
                                    ? 'bg-slate-900 border-slate-700 shadow-[0_0_20px_rgba(34,211,238,0.05)]'
                                    : 'bg-slate-950/40 border-slate-900/30 hover:bg-slate-900/40 hover:border-slate-800'}
                            `}
                        >
                            <div className="flex flex-col gap-1">
                                <span className={`text-base font-bold leading-none tracking-tight ${isSelected ? 'text-white' : 'text-slate-200'}`}>
                                    {symbol}
                                </span>
                                <span className="text-[10px] text-slate-800 font-bold uppercase tracking-widest">
                                    {name}
                                </span>
                            </div>

                            <div className="flex items-center gap-8">
                                {matchStr && (
                                    <div className="bg-slate-900/60 px-2.5 py-1 rounded-md border border-slate-900">
                                        <span className="text-[9px] font-mono font-bold text-slate-800 tracking-tight whitespace-nowrap">
                                            {matchStr.includes('Match') ? matchStr.toUpperCase() : `${matchStr.toUpperCase()} MATCH`}
                                        </span>
                                    </div>
                                )}

                                <div className={`
                                    w-4.5 h-4.5 rounded-full border-2 flex items-center justify-center transition-all bg-slate-950/60
                                    ${isSelected ? 'border-cyan-500 bg-cyan-500/10 shadow-[0_0_8px_rgba(34,211,238,0.2)]' : 'border-slate-800 bg-transparent group-hover:border-slate-700'}
                                `}>
                                    {isSelected && (
                                        <div className="w-1.5 h-1.5 bg-cyan-400 rounded-full shadow-[0_0_10px_rgba(34,211,238,1)]" />
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
    // Determine if this is a Ticker Resolution form to apply specific header
    const isTickerForm = title?.toLowerCase().includes('ticker') || schema.title?.toLowerCase().includes('ticker');

    return (
        <div className={`
            border rounded-xl overflow-hidden backdrop-blur-xl animate-in fade-in zoom-in-95 duration-500 shadow-xl
            ${isTickerForm
                ? 'bg-amber-500/[0.025] border-amber-500/20 shadow-amber-500/[0.01]'
                : 'bg-slate-950/20 border-slate-900'}
        `}>
            {/* Header section with accent color */}
            <div className={`px-5 py-4 flex items-center gap-4 border-b ${isTickerForm ? 'border-amber-500/10' : 'border-slate-800/50'}`}>
                <div className={`p-2 rounded-lg shrink-0 ${isTickerForm ? 'bg-amber-500/10 shadow-[0_0_10px_rgba(245,158,11,0.05)]' : 'bg-cyan-500/10'}`}>
                    {isTickerForm ? (
                        <Zap size={16} className="text-amber-500" />
                    ) : (
                        <AlertTriangle size={16} className="text-cyan-400" />
                    )}
                </div>
                <div>
                    <h3 className={`text-[10px] font-bold uppercase tracking-[0.2em] ${isTickerForm ? 'text-amber-500' : 'text-white'}`}>
                        {isTickerForm ? 'Ticker Resolution Required' : (title || schema.title || 'Action Required')}
                    </h3>
                    {(description || schema.description) && (
                        <p className="text-[10px] text-slate-800 font-bold mt-1 uppercase tracking-tight opacity-80">
                            {description || schema.description || 'Please select the correct company to proceed.'}
                        </p>
                    )}
                </div>
            </div>

            <div className="p-6">
                <div className="rjsf-container">
                    <Form
                        schema={schema}
                        uiSchema={{
                            ...uiSchema,
                            "ui:submitButtonOptions": {
                                "props": {
                                    "className": "w-full mt-4 bg-cyan-600 hover:bg-cyan-500 text-white text-[10px] font-bold py-3.5 rounded-lg transition-all uppercase tracking-[0.15em] shadow-xl shadow-cyan-500/10 border-none cursor-pointer flex items-center justify-center gap-2"
                                },
                                "submitText": "Confirm Selection"
                            }
                        }}
                        formData={formData}
                        widgets={widgets}
                        validator={validator}
                        onSubmit={({ formData }) => onSubmit(formData)}
                        className="space-y-4"
                    />
                </div>
            </div>

            <style jsx global>{`
                .rjsf-container .form-group {
                    margin-bottom: 0px;
                }
                .rjsf-container .field-object > label,
                .rjsf-container .field-string > label {
                    display: none;
                }
                .rjsf-container fieldset {
                    border: none;
                    padding: 0;
                    margin: 0;
                }
                .rjsf-container legend {
                    display: none;
                }
                .rjsf-container label {
                    display: block;
                    font-size: 10px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.1em;
                    color: #64748b; /* slate-500 */
                    margin-bottom: 0.75rem;
                }
                .rjsf-container input[type="text"],
                .rjsf-container textarea,
                .rjsf-container select {
                    width: 100%;
                    background: rgba(15, 23, 42, 0.6); /* slate-950/60 */
                    border: 1px solid #1e293b; /* slate-800 */
                    border-radius: 0.75rem;
                    padding: 0.875rem 1rem;
                    color: white;
                    font-size: 0.875rem;
                    transition: all 0.2s;
                    box-sizing: border-box;
                }
                .rjsf-container input:focus,
                .rjsf-container textarea:focus,
                .rjsf-container select:focus {
                    outline: none;
                    border-color: #06b6d4; /* cyan-500 */
                    background: rgba(15, 23, 42, 0.9);
                    box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.05);
                }
                .rjsf-container .field-description {
                    font-size: 10px;
                    color: #475569; /* slate-600 */
                    margin-top: 0.5rem;
                    font-weight: 500;
                }
                .rjsf-container .error-detail {
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
