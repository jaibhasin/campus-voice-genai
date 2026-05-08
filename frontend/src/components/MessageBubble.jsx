"use client";

import { motion } from "framer-motion";
import OptionPills from "./OptionPills";

/**
 * Parse [OPTIONS]...[/OPTIONS] blocks from agent text.
 * Returns { cleanText, options[] }
 */
function parseOptions(text) {
  const match = text.match(/\[OPTIONS\]\s*\n([\s\S]*?)\n\s*\[\/OPTIONS\]/);
  if (!match) return { cleanText: text, options: [] };

  const optionsRaw = match[1].trim();
  const options = optionsRaw
    .split("\n")
    .map((line) => line.replace(/^[-•]\s*/, "").trim())
    .filter(Boolean);

  const cleanText = text.slice(0, match.index).trimEnd();
  const trailing = text.slice(match.index + match[0].length).trim();

  return {
    cleanText: trailing ? `${cleanText}\n\n${trailing}` : cleanText,
    options,
  };
}

export default function MessageBubble({ message, isLast, onOptionClick }) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  // Parse options from assistant messages
  const { cleanText, options } = isAssistant
    ? parseOptions(message.content)
    : { cleanText: message.content, options: [] };

  return (
    <motion.div
      className={`message ${message.role}`}
      initial={{ opacity: 0, y: 16, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      layout
    >
      {/* Avatar */}
      <motion.div
        className="message-avatar"
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 400, damping: 20, delay: 0.1 }}
      >
        {isUser ? "👤" : "🎓"}
      </motion.div>

      {/* Content */}
      <div className="message-content">
        {/* Text */}
        {cleanText && (
          <div
            dangerouslySetInnerHTML={{
              __html: formatMarkdown(cleanText),
            }}
          />
        )}

        {/* Typing cursor while streaming */}
        {message.isStreaming && <span className="typing-cursor" />}

        {/* Option pills (only on last assistant message) */}
        {isAssistant && isLast && !message.isStreaming && options.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.3 }}
          >
            <OptionPills options={options} onSelect={onOptionClick} />
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

/**
 * Lightweight markdown-to-HTML converter for chat messages.
 * Handles: bold, italic, line breaks, bullet lists, inline code.
 */
function formatMarkdown(text) {
  let html = text
    // Escape HTML
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    // Bold
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    // Italic
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    // Inline code
    .replace(/`(.*?)`/g, "<code>$1</code>")
    // Line breaks → paragraphs
    .replace(/\n\n/g, "</p><p>")
    // Single newlines → <br>
    .replace(/\n/g, "<br/>")
    // Bullet points
    .replace(
      /(?:^|<br\/>)\s*[-•]\s+(.*?)(?=<br\/>|<\/p>|$)/g,
      '<li>$1</li>'
    );

  // Wrap loose <li> in <ul>
  html = html.replace(/(<li>.*?<\/li>)+/g, "<ul>$&</ul>");

  return `<p>${html}</p>`;
}
