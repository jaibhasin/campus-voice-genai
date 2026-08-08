"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * CallOverlay — Full-screen hands-free voice call with Scout.
 *
 * Features:
 * 1. Multilingual matching (STT language detection passed through to TTS and agent).
 * 2. 30-second inactivity check-in prompt if user is silent.
 * 3. Persistent, scrollable transcription history viewable throughout the call.
 */
export default function CallOverlay({ isOpen, onClose }) {
  const [callState, setCallState] = useState("connecting");
  // "connecting" | "listening" | "processing" | "thinking" | "speaking"

  const [callMessages, setCallMessages] = useState([]);
  const [callDuration, setCallDuration] = useState(0);

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const analyserRef = useRef(null);
  const audioRef = useRef(null);
  const activeRef = useRef(false);
  const threadIdRef = useRef(crypto.randomUUID());
  const durationTimerRef = useRef(null);
  const inactivityTimerRef = useRef(null);
  const detectedLanguageRef = useRef("en-IN");
  const messagesEndRef = useRef(null);

  // Auto-scroll transcript container to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [callMessages, callState]);

  // ── Call Duration Timer ──
  useEffect(() => {
    if (isOpen) {
      setCallDuration(0);
      setCallMessages([]);
      detectedLanguageRef.current = "en-IN";
      durationTimerRef.current = setInterval(() => {
        setCallDuration((d) => d + 1);
      }, 1000);
    } else {
      clearInterval(durationTimerRef.current);
      clearTimeout(inactivityTimerRef.current);
    }
    return () => {
      clearInterval(durationTimerRef.current);
      clearTimeout(inactivityTimerRef.current);
    };
  }, [isOpen]);

  const formatDuration = (s) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
  };

  // ── Silence Detection for Active Speech ──
  const startSilenceDetection = useCallback((stream) => {
    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = { analyser, audioCtx };

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      let silenceStart = null;
      const SILENCE_THRESHOLD = 15;
      const SILENCE_DURATION = 1800; // ms

      const check = () => {
        if (!activeRef.current) return;

        analyser.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

        if (avg < SILENCE_THRESHOLD) {
          if (!silenceStart) silenceStart = Date.now();
          else if (Date.now() - silenceStart > SILENCE_DURATION) {
            if (mediaRecorderRef.current?.state === "recording") {
              mediaRecorderRef.current.stop();
            }
            return;
          }
        } else {
          silenceStart = null;
        }

        requestAnimationFrame(check);
      };

      setTimeout(() => requestAnimationFrame(check), 600);
    } catch (e) {
      console.error("Silence detection error:", e);
    }
  }, []);

  // ── 30-Second Inactivity Check-in Prompt ──
  const handleInactivityPrompt = useCallback(async () => {
    if (!activeRef.current) return;

    const currentLang = detectedLanguageRef.current || "en-IN";
    const checkInText = currentLang.startsWith("hi")
      ? "मैं अभी भी आपकी बात सुन रहा हूँ! थापर यूनिवर्सिटी के बारे में आपका कोई भी सवाल है, तो आप पूछ सकते हैं।"
      : "I'm still here on call! Feel free to ask any question about admissions, fees, hostel, or campus life at TIET.";

    // Append to conversation log
    const msgId = crypto.randomUUID();
    setCallMessages((prev) => [
      ...prev,
      { id: msgId, role: "assistant", text: checkInText },
    ]);

    setCallState("speaking");

    try {
      const ttsResp = await fetch(`${API_URL}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: checkInText,
          language_code: currentLang,
          speaker: "shubh",
          model: "bulbul:v3",
        }),
      });
      const ttsData = await ttsResp.json();

      if (ttsData.audio_base64 && activeRef.current) {
        const audioSrc = `data:audio/wav;base64,${ttsData.audio_base64}`;
        const audio = new Audio(audioSrc);
        audioRef.current = audio;

        audio.onended = () => {
          if (activeRef.current) startListening();
        };
        audio.onerror = () => {
          if (activeRef.current) startListening();
        };

        await audio.play();
      } else {
        if (activeRef.current) startListening();
      }
    } catch (err) {
      console.error("Inactivity prompt TTS error:", err);
      if (activeRef.current) startListening();
    }
  }, []);

  // ── Start Listening Loop ──
  const startListening = useCallback(async () => {
    if (!activeRef.current) return;

    setCallState("listening");
    chunksRef.current = [];

    // Set 30-second timer for user response inactivity
    clearTimeout(inactivityTimerRef.current);
    inactivityTimerRef.current = setTimeout(() => {
      if (activeRef.current && mediaRecorderRef.current?.state === "recording") {
        console.log("[Inactivity] 30s elapsed without user speech");
        mediaRecorderRef.current.stop();
        handleInactivityPrompt();
      }
    }, 30000);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";

      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        // Clear 30s timer since recording stopped
        clearTimeout(inactivityTimerRef.current);

        // Stop current mic stream to prevent feedback
        stream.getTracks().forEach((t) => t.stop());

        if (!activeRef.current) return;

        const blob = new Blob(chunksRef.current, { type: "audio/webm" });

        // Ignore noise / tiny silence clips
        if (blob.size < 1000) {
          if (activeRef.current) startListening();
          return;
        }

        // ── 1. Speech-to-Text (STT) ──
        setCallState("processing");
        try {
          const formData = new FormData();
          formData.append("file", blob, "recording.webm");

          const sttResp = await fetch(`${API_URL}/api/stt`, {
            method: "POST",
            body: formData,
          });
          const sttData = await sttResp.json();

          if (!sttData.transcript || !sttData.transcript.trim()) {
            if (activeRef.current) startListening();
            return;
          }

          // Save detected spoken language (e.g., hi-IN, en-IN)
          if (sttData.language_code) {
            detectedLanguageRef.current = sttData.language_code;
          }

          const userText = sttData.transcript.trim();

          // Append user turn to persistent conversation log
          const userMsgId = crypto.randomUUID();
          setCallMessages((prev) => [
            ...prev,
            { id: userMsgId, role: "user", text: userText },
          ]);

          // ── 2. Chat Agent (SSE) ──
          setCallState("thinking");
          const assistantMsgId = crypto.randomUUID();

          // Append empty bot placeholder
          setCallMessages((prev) => [
            ...prev,
            { id: assistantMsgId, role: "assistant", text: "" },
          ]);

          const chatResp = await fetch(`${API_URL}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              message: userText,
              thread_id: threadIdRef.current,
            }),
          });

          const reader = chatResp.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          let fullResponse = "";

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
                  fullResponse += event.content;
                  setCallMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantMsgId
                        ? { ...msg, text: fullResponse }
                        : msg
                    )
                  );
                } else if (event.type === "done") {
                  fullResponse = event.full_content || fullResponse;
                  setCallMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantMsgId
                        ? { ...msg, text: fullResponse }
                        : msg
                    )
                  );
                }
              } catch (e) {
                // skip bad chunks
              }
            }
          }

          // ── 3. Text-to-Speech (TTS) ──
          if (!activeRef.current || !fullResponse.trim()) {
            if (activeRef.current) startListening();
            return;
          }

          setCallState("speaking");

          // Strip options / formatting for clear speech synthesis
          const cleanText = fullResponse
            .replace(/\[OPTIONS\][\s\S]*?\[\/OPTIONS\]/g, "")
            .replace(/\*\*(.*?)\*\*/g, "$1")
            .replace(/\*(.*?)\*/g, "$1")
            .replace(/`(.*?)`/g, "$1")
            .replace(/[#>*_~`]/g, "")
            .trim();

          const ttsResp = await fetch(`${API_URL}/api/tts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              text: cleanText,
              language_code: detectedLanguageRef.current || "en-IN",
              speaker: "shubh",
              model: "bulbul:v3",
            }),
          });
          const ttsData = await ttsResp.json();

          if (ttsData.audio_base64 && activeRef.current) {
            const audioSrc = `data:audio/wav;base64,${ttsData.audio_base64}`;
            const audio = new Audio(audioSrc);
            audioRef.current = audio;

            audio.onended = () => {
              if (activeRef.current) startListening();
            };
            audio.onerror = (err) => {
              console.error("[Audio Playback Error]", err);
              if (activeRef.current) startListening();
            };

            try {
              await audio.play();
            } catch (playErr) {
              console.error("[Audio Play Exception]", playErr);
              if (activeRef.current) startListening();
            }
          } else {
            console.warn("[TTS Warning] No audio returned:", ttsData);
            if (activeRef.current) startListening();
          }
        } catch (err) {
          console.error("Call flow error:", err);
          if (activeRef.current) startListening();
        }
      };

      recorder.start();
      startSilenceDetection(stream);
    } catch (err) {
      console.error("Mic access error:", err);
      handleEndCall();
    }
  }, [startSilenceDetection, handleInactivityPrompt]);

  // ── Initiate Call Session ──
  useEffect(() => {
    if (isOpen) {
      activeRef.current = true;
      threadIdRef.current = crypto.randomUUID();
      setTimeout(() => startListening(), 600);
    }
    return () => {
      activeRef.current = false;
      clearTimeout(inactivityTimerRef.current);
    };
  }, [isOpen, startListening]);

  // ── Terminate Call Session ──
  const handleEndCall = useCallback(() => {
    activeRef.current = false;
    setCallState("connecting");
    clearTimeout(inactivityTimerRef.current);

    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    if (analyserRef.current?.audioCtx) {
      analyserRef.current.audioCtx.close();
      analyserRef.current = null;
    }

    onClose();
  }, [onClose]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        className="call-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.3 }}
      >
        <div className="call-screen">
          {/* Top Bar */}
          <div className="call-top-bar">
            <span className="call-duration">{formatDuration(callDuration)}</span>
            <span className="call-encrypted">🔒 Live Audio Call</span>
          </div>

          {/* Avatar Header */}
          <div className="call-header-center">
            <motion.div
              className="call-avatar"
              animate={
                callState === "speaking"
                  ? { scale: [1, 1.08, 1], boxShadow: ["0 0 0px #e67e22", "0 0 35px #e67e22", "0 0 0px #e67e22"] }
                  : callState === "listening"
                  ? { scale: [1, 1.04, 1], boxShadow: ["0 0 0px #27ae60", "0 0 25px #27ae60", "0 0 0px #27ae60"] }
                  : {}
              }
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
            >
              🎓
            </motion.div>

            <h2 className="call-name">Scout</h2>
            <p className="call-subtitle">TIET College Assistant</p>

            {/* Current Dynamic Status */}
            <div className="call-status-text">
              {callState === "connecting" && "Connecting..."}
              {callState === "listening" && "🎤 Listening... speak freely"}
              {callState === "processing" && "⏳ Transcribing audio..."}
              {callState === "thinking" && "💭 Scout is thinking..."}
              {callState === "speaking" && "🔊 Speaking response..."}
            </div>
          </div>

          {/* Scrollable Conversation History (Kept visible all through call) */}
          <div className="call-conversation-list">
            {callMessages.length === 0 ? (
              <div className="call-history-empty">
                <p>Start speaking naturally. Your transcript and Scout&apos;s responses will stay here throughout the call.</p>
              </div>
            ) : (
              callMessages.map((msg) => (
                <motion.div
                  key={msg.id}
                  className={`call-msg-bubble ${msg.role}`}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                >
                  <span className="call-msg-label">
                    {msg.role === "user" ? "You" : "Scout"}
                  </span>
                  <p>{msg.text || "..."}</p>
                </motion.div>
              ))
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* End Call Button */}
          <div className="call-bottom-action">
            <motion.button
              className="call-end-btn"
              onClick={handleEndCall}
              whileHover={{ scale: 1.06 }}
              whileTap={{ scale: 0.94 }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91" />
                <line x1="23" y1="1" x2="1" y2="23" />
              </svg>
            </motion.button>
            <span className="call-end-label">End Call</span>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
