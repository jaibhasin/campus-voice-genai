"use client";

import { useRef, useEffect, useState } from "react";
import { AnimatePresence } from "framer-motion";
import MessageBubble from "./MessageBubble";
import WelcomeCard from "./WelcomeCard";
import ThinkingState from "./ThinkingState";

export default function ChatWindow({ messages, onSend, isStreaming }) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Check if the agent is "thinking" (streaming but no content yet)
  const lastMsg = messages[messages.length - 1];
  const isThinking =
    isStreaming &&
    lastMsg?.role === "assistant" &&
    lastMsg?.isStreaming &&
    !lastMsg?.content;

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

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
    <main className="chat-main">
      {/* Messages */}
      <div className="messages-container">
        {messages.length === 0 ? (
          <WelcomeCard />
        ) : (
          <>
            {messages.map((msg, idx) => {
              // Don't render the empty assistant placeholder while thinking
              if (
                msg.role === "assistant" &&
                msg.isStreaming &&
                !msg.content
              ) {
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

            {/* Thinking state — shown while agent processes */}
            <AnimatePresence>
              {isThinking && <ThinkingState />}
            </AnimatePresence>
          </>
        )}
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
    </main>
  );
}
