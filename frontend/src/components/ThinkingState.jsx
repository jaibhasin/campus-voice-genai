"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import thaparFacts from "@/thaparfacts.json";

/**
 * ThinkingState — shown while the agent processes the query.
 * Features a CSS robot avatar + rotating "Did you know?" TIET facts.
 */
export default function ThinkingState() {
  const [factIndex, setFactIndex] = useState(() =>
    Math.floor(Math.random() * thaparFacts.length)
  );

  // Rotate facts every 3 seconds
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
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10, transition: { duration: 0.2 } }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      <div className="thinking-layout">
        {/* Robot Avatar */}
        <div className="robot-container">
          <RobotAvatar />
        </div>

        {/* Status + Facts */}
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
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.4 }}
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

/**
 * Pure CSS/SVG robot avatar with idle animations.
 * No Three.js dependency — lightweight and performant.
 */
function RobotAvatar() {
  return (
    <div className="robot">
      {/* Antenna */}
      <div className="robot-antenna">
        <div className="robot-antenna-rod" />
        <div className="robot-antenna-orb" />
      </div>

      {/* Head */}
      <div className="robot-head">
        <div className="robot-visor">
          <div className="robot-eye robot-eye-left" />
          <div className="robot-eye robot-eye-right" />
        </div>
        <div className="robot-ear robot-ear-left" />
        <div className="robot-ear robot-ear-right" />
      </div>

      {/* Neck */}
      <div className="robot-neck" />

      {/* Body */}
      <div className="robot-body">
        <div className="robot-chest-light" />
      </div>
    </div>
  );
}
