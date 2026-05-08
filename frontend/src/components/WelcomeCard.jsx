"use client";

import { motion } from "framer-motion";

export default function WelcomeCard() {
  return (
    <motion.div
      className="welcome-card"
      initial={{ opacity: 0, y: 30, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.6, ease: "easeOut" }}
    >
      <motion.h2
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2, duration: 0.4 }}
      >
        👋 Welcome to Scout
      </motion.h2>
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4, duration: 0.4 }}
      >
        Your intelligent assistant for all TIET queries.
        <br />
        Type a question below or pick one from the sidebar to get started.
      </motion.p>
    </motion.div>
  );
}
