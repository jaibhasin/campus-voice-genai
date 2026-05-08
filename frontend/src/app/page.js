"use client";

import { useState, useRef, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import ChatWindow from "@/components/ChatWindow";

export default function Home() {
  const [messages, setMessages] = useState([]);
  const [threadId] = useState(() => crypto.randomUUID());
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef(null);

  const sendMessage = useCallback(
    async (text) => {
      if (!text.trim() || isStreaming) return;

      // Add user message
      const userMsg = { role: "user", content: text };
      setMessages((prev) => [...prev, userMsg]);

      // Add empty assistant message (will be filled via streaming)
      const assistantMsg = {
        role: "assistant",
        content: "",
        isStreaming: true,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setIsStreaming(true);

      try {
        abortRef.current = new AbortController();
        const res = await fetch("http://localhost:8000/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, thread_id: threadId }),
          signal: abortRef.current.signal,
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;

            try {
              const event = JSON.parse(jsonStr);

              if (event.type === "token") {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = { ...updated[updated.length - 1] };
                  last.content += event.content;
                  updated[updated.length - 1] = last;
                  return updated;
                });
              } else if (event.type === "tool_call") {
                // Silently skip tool call events — not shown in UI
              } else if (event.type === "done") {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = { ...updated[updated.length - 1] };
                  last.content = event.full_content || last.content;
                  last.isStreaming = false;
                  updated[updated.length - 1] = last;
                  return updated;
                });
              } else if (event.type === "error") {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = { ...updated[updated.length - 1] };
                  last.content = `⚠️ Error: ${event.message}`;
                  last.isStreaming = false;
                  updated[updated.length - 1] = last;
                  return updated;
                });
              }
            } catch {
              // skip malformed JSON
            }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = { ...updated[updated.length - 1] };
            last.content = "⚠️ Failed to connect to the server. Is the backend running?";
            last.isStreaming = false;
            updated[updated.length - 1] = last;
            return updated;
          });
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [threadId, isStreaming]
  );

  const handleNewConversation = () => {
    setMessages([]);
  };

  return (
    <div className="app-layout">
      <Sidebar
        onQuickQuestion={sendMessage}
        onNewConversation={handleNewConversation}
      />
      <ChatWindow
        messages={messages}
        onSend={sendMessage}
        isStreaming={isStreaming}
      />
    </div>
  );
}
