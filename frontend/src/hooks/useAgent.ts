'use client';

import { useState, useCallback, useRef } from 'react';

export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
}

export interface Interrupt {
    type: string;
    data: any;
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

                        // Handle Token Streaming (on_chat_model_stream)
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

                        // Handle State Updates & Interrupts (on_chain_stream)
                        if (eventData.event === 'on_chain_stream' || eventData.event === 'on_chain_end') {
                            const chunk = eventData.data?.chunk || eventData.data?.output;
                            if (chunk && typeof chunk === 'object') {
                                // 1. Check for Messages (for non-streaming nodes like Calculator)
                                if (chunk.messages && Array.isArray(chunk.messages) && chunk.messages.length > 0) {
                                    const lastMsg = chunk.messages[chunk.messages.length - 1];
                                    // Only add if it's an AIMessage and content is a string
                                    if (lastMsg.type === 'ai' && typeof lastMsg.content === 'string') {
                                        const msgContent = lastMsg.content;
                                        setMessages((prev) => {
                                            // Dedup: if the last message in state is identical/streaming, maybe merge?
                                            // But for calculator, it's a new message.
                                            // Simple check: avoid adding if ID exists or consistent content
                                            // Since we generate IDs in frontend, checking content might be enough for now 
                                            // or let's just append it as a new "Answer"

                                            // Avoid duplicates if on_chain_stream fires multiple times
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

                                // 2. Check for interrupt markers
                                // The new backend might send it in a specific field or as __interrupt__
                                if ('__interrupt__' in chunk) {
                                    const interruptVal = (chunk as any).__interrupt__[0]?.value;
                                    setInterrupt({
                                        type: interruptVal?.type || 'unknown',
                                        data: interruptVal
                                    });
                                }
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
            const response = await fetch(`${API_URL}/agent/stream_events`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Thread-ID': currentThreadId
                },
                body: JSON.stringify({
                    input: { user_query: content },
                    version: 'v2'
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
        console.log("🚀 submitCommand called with payload:", payload, "ThreadID:", threadId);
        if (!threadId) {
            console.error("❌ ThreadID is missing in submitCommand");
            return;
        }
        setIsLoading(true);
        setInterrupt(null);

        try {
            console.log("🌐 Fetching /agent/resume...");
            const response = await fetch(`${API_URL}/agent/resume`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Thread-ID': threadId
                },
                body: JSON.stringify({ payload })
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            await parseStream(response, `ai_resume_${Date.now()}`);
        } catch (error) {
            console.error("Resume error:", error);
        } finally {
            console.log("🔒 submitCommand finally - Setting isLoading to false");
            setIsLoading(false);
        }
    }, [threadId]);

    return { messages, sendMessage, submitCommand, isLoading, threadId, interrupt };
}
