"use client";

import { useState, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import ChatWidget from "@/components/ChatWidget";
import CallOverlay from "@/components/CallOverlay";
import ProviderSelect from "@/components/ProviderSelect";

const QUICK_QUESTIONS = [
  { emoji: "📋", text: "How do I apply for admission?" },
  { emoji: "💰", text: "What is the B.Tech fee structure?" },
  { emoji: "🏠", text: "What are the hostel charges?" },
  { emoji: "🎓", text: "What scholarships are available?" },
  { emoji: "🌍", text: "Tell me about international exchange programs" },
];

export default function Home() {
  const [messages, setMessages] = useState([]);
  const [threadId] = useState(() => crypto.randomUUID());
  const [isStreaming, setIsStreaming] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isCallOpen, setIsCallOpen] = useState(false);
  const [retrievalProvider, setRetrievalProvider] = useState("llm_batch");
  const abortRef = useRef(null);

  const sendMessage = useCallback(
    async (text) => {
      if (!text.trim() || isStreaming) return;

      // Open chat widget if not open
      if (!isChatOpen) setIsChatOpen(true);

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
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text, thread_id: threadId, retrieval_provider: retrievalProvider,
          }),
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
                // Silently skip tool call events
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
            last.content =
              "⚠️ Failed to connect to the server. Is the backend running?";
            last.isStreaming = false;
            updated[updated.length - 1] = last;
            return updated;
          });
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [threadId, isStreaming, isChatOpen, retrievalProvider]
  );

  const handleNewConversation = () => {
    setMessages([]);
  };

  return (
    <>
      {/* Blurred Background Image */}
      <div className="bg-image" />
      <div className="bg-overlay" />

      {/* Landing Content */}
      <main className="landing">
        <motion.div
          className="landing-content"
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: "easeOut" }}
        >
          <motion.div
            className="landing-badge"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2, duration: 0.4 }}
          >
            🎓 TIET College Assistant
          </motion.div>

          <motion.h1
            className="landing-title"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.5 }}
          >
            Welcome to <span className="accent">Scout</span>
          </motion.h1>

          <motion.p
            className="landing-subtitle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5, duration: 0.4 }}
          >
            Your AI-powered assistant for everything about
            <br />
            <strong>Thapar Institute of Engineering & Technology</strong>
          </motion.p>

          <motion.div
            className="quick-buttons"
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.7, duration: 0.5 }}
          >
            {QUICK_QUESTIONS.map((q, i) => (
              <motion.button
                key={i}
                className="quick-btn"
                onClick={() => sendMessage(q.text)}
                whileHover={{ scale: 1.04, y: -2 }}
                whileTap={{ scale: 0.97 }}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.8 + i * 0.08, duration: 0.3 }}
              >
                <span className="quick-btn-emoji">{q.emoji}</span>
                <span>{q.text}</span>
              </motion.button>
            ))}
          </motion.div>

          {/* Call Scout button */}
          <motion.button
            className="call-scout-btn"
            onClick={() => setIsCallOpen(true)}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1.0, duration: 0.4 }}
            whileHover={{ scale: 1.05, y: -2 }}
            whileTap={{ scale: 0.97 }}
          >
            <span className="call-scout-icon">📞</span>
            <span>Call Scout</span>
          </motion.button>
          <div className="landing-provider">
            <ProviderSelect
              value={retrievalProvider}
              onChange={setRetrievalProvider}
              disabled={isStreaming || isCallOpen}
            />
          </div>
        </motion.div>
      </main>

      {/* Floating Chat Widget */}
      <ChatWidget
        messages={messages}
        onSend={sendMessage}
        isStreaming={isStreaming}
        isOpen={isChatOpen}
        onToggle={() => setIsChatOpen(!isChatOpen)}
        onNewConversation={handleNewConversation}
      />

      {/* Full-screen Call Overlay */}
      <CallOverlay
        isOpen={isCallOpen}
        onClose={() => setIsCallOpen(false)}
        retrievalProvider={retrievalProvider}
      />
    </>
  );
}
