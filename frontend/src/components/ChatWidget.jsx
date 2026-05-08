"use client";

import { useRef, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import MessageBubble from "./MessageBubble";
import ThinkingState from "./ThinkingState";

export default function ChatWidget({
  messages,
  onSend,
  isStreaming,
  isOpen,
  onToggle,
  onNewConversation,
}) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Check if agent is "thinking" (streaming but no content yet)
  const lastMsg = messages[messages.length - 1];
  const isThinking =
    isStreaming &&
    lastMsg?.role === "assistant" &&
    lastMsg?.isStreaming &&
    !lastMsg?.content;

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  // Focus input when chat opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 300);
    }
  }, [isOpen]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    onSend(input.trim());
    setInput("");
  };

  const handleOptionClick = (option) => {
    onSend(option);
  };

  return (
    <>
      {/* Floating Toggle Button */}
      <AnimatePresence>
        {!isOpen && (
          <motion.button
            className="chat-fab"
            onClick={onToggle}
            initial={{ scale: 0, rotate: -180 }}
            animate={{ scale: 1, rotate: 0 }}
            exit={{ scale: 0, rotate: 180 }}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
            transition={{ type: "spring", stiffness: 300, damping: 20 }}
            aria-label="Open chat"
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </motion.button>
        )}
      </AnimatePresence>

      {/* Chat Panel */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            className="chat-panel"
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          >
            {/* Header */}
            <div className="chat-header">
              <div className="chat-header-info">
                <div className="chat-header-avatar">🎓</div>
                <div>
                  <div className="chat-header-name">Scout</div>
                  <div className="chat-header-status">
                    <span className="status-dot" />
                    Online
                  </div>
                </div>
              </div>
              <div className="chat-header-actions">
                <button
                  className="chat-header-btn"
                  onClick={onNewConversation}
                  title="New conversation"
                >
                  🔄
                </button>
                <button
                  className="chat-header-btn"
                  onClick={onToggle}
                  title="Close"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Messages */}
            <div className="chat-messages">
              {messages.length === 0 && (
                <motion.div
                  className="chat-empty"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.2 }}
                >
                  <div className="chat-empty-icon">👋</div>
                  <p>Hi! I&apos;m Scout, your TIET assistant.</p>
                  <p className="chat-empty-hint">Ask me anything about admissions, fees, hostel, and more!</p>
                </motion.div>
              )}

              {messages.map((msg, idx) => {
                if (msg.role === "assistant" && msg.isStreaming && !msg.content) {
                  return null;
                }
                return (
                  <MessageBubble
                    key={idx}
                    message={msg}
                    isLast={idx === messages.length - 1}
                    onOptionClick={handleOptionClick}
                  />
                );
              })}

              <AnimatePresence>
                {isThinking && <ThinkingState />}
              </AnimatePresence>

              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="chat-input-area">
              <form className="chat-input-wrapper" onSubmit={handleSubmit}>
                <input
                  ref={inputRef}
                  className="chat-input"
                  type="text"
                  placeholder="Ask me anything about TIET..."
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  disabled={isStreaming}
                />
                <button
                  className="send-btn"
                  type="submit"
                  disabled={!input.trim() || isStreaming}
                  aria-label="Send message"
                >
                  ↑
                </button>
              </form>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
