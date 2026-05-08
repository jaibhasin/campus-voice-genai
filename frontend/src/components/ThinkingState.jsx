"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import thaparFacts from "@/thaparfacts.json";

export default function ThinkingState() {
  const [factIndex, setFactIndex] = useState(() =>
    Math.floor(Math.random() * thaparFacts.length)
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setFactIndex((prev) => (prev + 1) % thaparFacts.length);
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const fact = thaparFacts[factIndex];

  return (
    <motion.div
      className="thinking-state"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8, transition: { duration: 0.2 } }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      <div className="thinking-layout">
        {/* Compact Robot */}
        <div className="robot-container">
          <div className="robot-mini">
            <div className="robot-mini-antenna">
              <div className="robot-mini-orb" />
            </div>
            <div className="robot-mini-head">
              <div className="robot-mini-visor">
                <div className="robot-mini-eye" />
                <div className="robot-mini-eye" />
              </div>
            </div>
            <div className="robot-mini-body">
              <div className="robot-mini-light" />
            </div>
          </div>
        </div>

        {/* Info */}
        <div className="thinking-info">
          <motion.div
            className="thinking-label"
            animate={{ opacity: [0.7, 1, 0.7] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          >
            <span>Scout is thinking</span>
            <span className="dot-pulse">
              <span />
              <span />
              <span />
            </span>
          </motion.div>

          <div className="fact-label">✨ DID YOU KNOW?</div>

          <AnimatePresence mode="wait">
            <motion.div
              key={factIndex}
              className="fact-card"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.35 }}
            >
              <span className="fact-emoji">{fact.emoji}</span>
              <span className="fact-text">{fact.text}</span>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
