'use client';

import { useState, useCallback, useRef } from 'react';

import { Interrupt } from '../types/interrupts';

export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
}

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export function useAgent(assistantId: string = "agent") {
    const [messages, setMessages] = useState<Message[]>([]);
    const [threadId, setThreadId] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [interrupt, setInterrupt] = useState<Interrupt | null>(null);

    const messagesRef = useRef<Message[]>([]);
    messagesRef.current = messages;

    const parseStream = async (response: Response, currentAiMsgId: string) => {
        const reader = response.body?.getReader();
        if (!reader) return;

        const decoder = new TextDecoder();
        let buffer = '';

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    console.log("✅ Stream reader done");
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    console.log("📩 SSE Line:", line);
                    if (!line.trim() || !line.startsWith('data: ')) continue;
                    try {
                        const eventData = JSON.parse(line.slice(6));

                        // 1. Handle Token Streaming (on_chat_model_stream)
                        if (eventData.event === 'on_chat_model_stream') {
                            const chunk = eventData.data?.chunk;
                            if (chunk?.content) {
                                const text = typeof chunk.content === 'string'
                                    ? chunk.content
                                    : chunk.content[0]?.text || '';

                                if (text) {
                                    setMessages((prev) => {
                                        const lastIdx = prev.length - 1;
                                        const lastMsg = prev[lastIdx];
                                        if (lastMsg && lastMsg.role === 'assistant' && lastMsg.id === currentAiMsgId) {
                                            const newMsgs = [...prev];
                                            newMsgs[lastIdx] = { ...lastMsg, content: lastMsg.content + text };
                                            return newMsgs;
                                        } else {
                                            return [...prev, { id: currentAiMsgId, role: 'assistant', content: text }];
                                        }
                                    });
                                }
                            }
                        }

                        // 2. Handle Messages from non-streaming nodes (on_chain_stream)
                        if (eventData.event === 'on_chain_stream' || eventData.event === 'on_chain_end') {
                            const chunk = eventData.data?.chunk || eventData.data?.output;
                            if (chunk && typeof chunk === 'object') {
                                if (chunk.messages && Array.isArray(chunk.messages) && chunk.messages.length > 0) {
                                    const lastMsg = chunk.messages[chunk.messages.length - 1];
                                    if (lastMsg.type === 'ai' && typeof lastMsg.content === 'string') {
                                        const msgContent = lastMsg.content;
                                        setMessages((prev) => {
                                            const lastStateMsg = prev[prev.length - 1];
                                            if (lastStateMsg && lastStateMsg.content === msgContent) {
                                                return prev;
                                            }
                                            return [...prev, {
                                                id: `ai_final_${Date.now()}`,
                                                role: 'assistant',
                                                content: msgContent
                                            }];
                                        });
                                    }
                                }
                            }
                        }

                        // 3. Handle Explicit Interrupt Event
                        // This handles both the custom 'interrupt' event and standard LangGraph interrupts
                        // if they are serialized as an array of objects with a 'type' field.

                        if (Array.isArray(eventData)) {
                            // This is likely the interrupt payload
                            const interruptVal = eventData[0] as Interrupt;
                            if (interruptVal && interruptVal.type) {
                                console.log("⏸️ Interrupt Detected:", interruptVal);
                                setInterrupt(interruptVal);
                            }
                        }

                    } catch (e) {
                        // console.error("Error parsing SSE line:", line, e);
                    }
                }
            }
        } finally {
            reader.releaseLock();
        }
    };

    const sendMessage = useCallback(async (content: string) => {
        setIsLoading(true);
        setInterrupt(null);

        let currentThreadId = threadId;
        if (!currentThreadId) {
            currentThreadId = `thread_${Date.now()}`;
            setThreadId(currentThreadId);
        }

        // Add user message optimistically
        const userMsg: Message = { id: `user_${Date.now()}`, role: 'user', content };
        setMessages(prev => [...prev, userMsg]);

        try {
            console.log(`🌐 Sending Message to /stream: ${content}`);
            const response = await fetch(`${API_URL}/stream`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    thread_id: currentThreadId,
                    message: content
                })
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            await parseStream(response, `ai_${Date.now()}`);
        } catch (error) {
            console.error("Agent stream error:", error);
        } finally {
            setIsLoading(false);
        }
    }, [threadId]);

    const submitCommand = useCallback(async (payload: any) => {
        console.log("🚀 submitCommand called (Resuming)", payload);
        if (!threadId) {
            console.error("❌ ThreadID is missing in submitCommand");
            return;
        }

        // --- NEW: Optimistically add user interaction to history ---
        let interactionText = "Resumed execution";
        if (payload.selected_symbol) {
            interactionText = `Selected Ticker: ${payload.selected_symbol}`;
        } else if (typeof payload.approved === 'boolean') {
            interactionText = payload.approved ? "✅ Approved Audit Plan" : "❌ Rejected Audit Plan";
        }

        const interactionMsg: Message = {
            id: `user_action_${Date.now()}`,
            role: 'user',
            content: interactionText
        };
        setMessages(prev => [...prev, interactionMsg]);
        // -----------------------------------------------------------

        setIsLoading(true);
        setInterrupt(null);

        try {
            console.log("🌐 Sending Resume to /stream...");
            const response = await fetch(`${API_URL}/stream`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    thread_id: threadId,
                    resume_payload: payload
                })
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            await parseStream(response, `ai_resume_${Date.now()}`);
        } catch (error) {
            console.error("Resume error:", error);
        } finally {
            setIsLoading(false);
        }
    }, [threadId]);

    return { messages, sendMessage, submitCommand, isLoading, threadId, interrupt };
}
