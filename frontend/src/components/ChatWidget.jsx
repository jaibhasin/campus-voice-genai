"use client";

import { useRef, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import MessageBubble from "./MessageBubble";
import ThinkingState from "./ThinkingState";

const PEEK_MESSAGES = [
  { text: "🎓 Take admission into <strong>Thapar</strong> — shape your future!" },
  { text: "🏛️ Wow, such an <strong>amazing campus life</strong> at TIET!" },
  { text: "🚀 Did you know? TIET alumni work at <strong>Google, Microsoft & Amazon</strong>!" },
  { text: "🌍 <strong>25+ international</strong> university collaborations await you!" },
  { text: "💡 Got questions about <strong>fees or hostel</strong>? Just ask me!" },
  { text: "🏆 TIET is in <strong>India's Top 30</strong> engineering institutes!" },
  { text: "📚 <strong>250 acres</strong> of campus with world-class facilities!" },
  { text: "🤝 Join the <strong>60,000+</strong> strong alumni network!" },
];

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

  // Peeking robot state — shows after 8s of inactivity
  const [showPeek, setShowPeek] = useState(false);
  const [peekMsgIndex, setPeekMsgIndex] = useState(0);
  const idleTimerRef = useRef(null);

  // Check if agent is "thinking"
  const lastMsg = messages[messages.length - 1];
  const isThinking =
    isStreaming &&
    lastMsg?.role === "assistant" &&
    lastMsg?.isStreaming &&
    !lastMsg?.content;

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  // Focus input when chat opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 300);
    }
  }, [isOpen]);

  // Idle timer — show peeking robot after 8s of no new messages
  useEffect(() => {
    if (!isOpen || isStreaming) {
      setShowPeek(false);
      return;
    }

    // Only trigger if there are messages (conversation happened)
    if (messages.length === 0) {
      setShowPeek(false);
      return;
    }

    clearTimeout(idleTimerRef.current);
    setShowPeek(false);

    idleTimerRef.current = setTimeout(() => {
      setShowPeek(true);
      setPeekMsgIndex(Math.floor(Math.random() * PEEK_MESSAGES.length));
    }, 8000);

    return () => clearTimeout(idleTimerRef.current);
  }, [messages, isOpen, isStreaming]);

  // Rotate peek messages every 5s
  useEffect(() => {
    if (!showPeek) return;
    const interval = setInterval(() => {
      setPeekMsgIndex((prev) => (prev + 1) % PEEK_MESSAGES.length);
    }, 5000);
    return () => clearInterval(interval);
  }, [showPeek]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    onSend(input.trim());
    setInput("");
    setShowPeek(false);
  };

  const handleOptionClick = (option) => {
    onSend(option);
    setShowPeek(false);
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

      {/* Peeking Robot — separate overlay outside chat panel */}
      <AnimatePresence>
        {isOpen && showPeek && (
          <motion.div
            className="peek-robot-wrapper"
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 20, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
          >
            <AnimatePresence mode="wait">
              <motion.div
                key={peekMsgIndex}
                className="peek-speech-bubble"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.3 }}
              >
                <span
                  className="peek-speech-text"
                  dangerouslySetInnerHTML={{
                    __html: PEEK_MESSAGES[peekMsgIndex].text,
                  }}
                />
              </motion.div>
            </AnimatePresence>

            <motion.div
              className="peek-robot-body"
              animate={{ y: [0, -3, 0] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            >
              <div className="peek-head">
                <div className="peek-antenna">
                  <div className="peek-antenna-orb" />
                </div>
                <div className="peek-visor">
                  <div className="peek-eye" />
                  <div className="peek-eye" />
                </div>
              </div>
              <div className="peek-hands">
                <div className="peek-hand" />
                <div className="peek-hand" />
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
