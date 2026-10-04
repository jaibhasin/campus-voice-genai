"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import VoiceOrb from "./VoiceOrb";

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
  const [connectionError, setConnectionError] = useState("");
  // "connecting" | "listening" | "processing" | "thinking" | "speaking"

  const [callMessages, setCallMessages] = useState([]);
  const [callDuration, setCallDuration] = useState(0);
  const wsRef = useRef(null);                     // WebSocket connection
  const audioCtxRef = useRef(null);               // AudioContext for mic capture
  const processorRef = useRef(null);              // ScriptProcessor for raw PCM
  const micStreamRef = useRef(null);              // Mic stream
  const activeRef = useRef(false);
  const threadIdRef = useRef(crypto.randomUUID());
  const durationTimerRef = useRef(null);
  const inactivityTimerRef = useRef(null);
  const detectedLanguageRef = useRef("en-IN");
  const messagesEndRef = useRef(null);

  // Audio playback queue (sequential decoded audio buffers, gapless playback via Web Audio API)
  const audioPlaybackQueue = useRef([]);
  const isPlayingAudioRef = useRef(false);
  const playbackSourceRef = useRef(null);         // Current AudioBufferSourceNode
  const playbackSourcesRef = useRef(new Set());  // All scheduled sources
  const playbackGenerationRef = useRef(0);        // Invalidates old finish timers
  const playbackDecodeChainRef = useRef(Promise.resolve()); // Preserves audio chunk order
  const playbackStartTimeRef = useRef(0);          // When current playback started (context time)
  const playbackAnalyserRef = useRef(null);
  const playbackCtxRef = useRef(null);              // Shared AudioContext for playback


  // Auto-scroll transcript container to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [callMessages, callState]);

  // ── Call Duration Timer ──
  useEffect(() => {
    if (isOpen) {
      setCallDuration(0);
      setCallMessages([]);
      setConnectionError("");
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


// ── 30-Second Inactivity Check-in Prompt ──
  const handleInactivityPrompt = useCallback(async () => {
    if (!activeRef.current || !wsRef.current) return;

    const currentLang = detectedLanguageRef.current || "en-IN";
    const checkInText = currentLang.startsWith("hi")
      ? "मैं अभी भी आपकी बात सुन रहा हूँ! थापर यूनिवर्सिटी के बारे में आपका कोई भी सवाल है, तो आप पूछ सकते हैं।"
      : "I'm still here on call! Feel free to ask any question about admissions, fees, hostel, or campus life at TIET.";

    const msgId = crypto.randomUUID();
    setCallMessages((prev) => [
      ...prev,
      { id: msgId, role: "assistant", text: checkInText },
    ]);

    setCallState("speaking");

    // Use the same TTS helper as agent responses
    sendTextToBackendTTS(checkInText, currentLang);
  }, []);  

  // ── Convert Float32 PCM to 16-bit PCM bytes ──
function float32ToPcm16(float32Array) {
  const len = float32Array.length;
  const buffer = new ArrayBuffer(len * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < len; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buffer);
}

// ── Send text to backend TTS over WebSocket ──
const sendTextToBackendTTS = useCallback((text, lang) => {
  if (!wsRef.current) return;
  wsRef.current.send(JSON.stringify({
    type: "tts",
    text: text,
    language_code: lang || "en-IN",
  }));
}, []);

// ── Start raw PCM audio capture → WebSocket ──
function startAudioCapture(stream, ws) {
  // Use default AudioContext sample rate (browser picks its native rate).
  // We'll resample to 16 kHz ourselves rather than trusting the hint.
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  audioCtxRef.current = audioCtx;
  const inputSampleRate = audioCtx.sampleRate;
  const targetSampleRate = 16000;
  const resampleRatio = targetSampleRate / inputSampleRate;

  const source = audioCtx.createMediaStreamSource(stream);
  const gainNode = audioCtx.createGain();
  gainNode.gain.value = 1;
  source.connect(gainNode);

  // ScriptProcessor is deprecated but still widely supported
  // AudioWorklet is the modern alternative if you want lower latency
  const bufferSize = 4096;
  const processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
  processorRef.current = processor;

  // Accumulate samples for resampling (linear interpolation)
  let accumBuffer = [];

  processor.onaudioprocess = (e) => {
    if (ws.readyState !== WebSocket.OPEN) return;

    const inputData = e.inputBuffer.getChannelData(0);
    accumBuffer.push(...inputData);

    // Resample accumulated samples to 16 kHz using linear interpolation
    const totalSamples = accumBuffer.length;
    const outputLen = Math.floor(totalSamples * resampleRatio);
    if (outputLen < 1) return; // not enough samples yet

    const output = new Float32Array(outputLen);
    for (let i = 0; i < outputLen; i++) {
      const srcIdx = i / resampleRatio;
      const idxLow = Math.floor(srcIdx);
      const frac = srcIdx - idxLow;
      if (idxLow + 1 < totalSamples) {
        output[i] = accumBuffer[idxLow] + frac * (accumBuffer[idxLow + 1] - accumBuffer[idxLow]);
      } else {
        output[i] = accumBuffer[idxLow] || 0;
      }
    }

    // Keep any leftover samples for next callback
    const consumed = Math.floor(outputLen / resampleRatio);
    accumBuffer = accumBuffer.slice(consumed);

    const pcm16Bytes = float32ToPcm16(output);
    ws.send(pcm16Bytes);
  };

  gainNode.connect(processor);
  processor.connect(audioCtx.destination);
}

// ── Audio playback queue (gapless via Web Audio API) ──
function playAudioChunk(arrayBuffer) {
  const playbackGeneration = playbackGenerationRef.current;
  if (!playbackCtxRef.current) {
    playbackCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = playbackCtxRef.current.createAnalyser();
    analyser.fftSize = 256;
    analyser.connect(playbackCtxRef.current.destination);
    playbackAnalyserRef.current = analyser;
    playbackStartTimeRef.current = playbackCtxRef.current.currentTime;
  }
  const ctx = playbackCtxRef.current;

  playbackDecodeChainRef.current = playbackDecodeChainRef.current.then(async () => {
    if (playbackGeneration !== playbackGenerationRef.current) return;
    try {
      const buffer = await ctx.decodeAudioData(arrayBuffer.slice(0));
      if (playbackGeneration !== playbackGenerationRef.current) return;

      isPlayingAudioRef.current = true;
      setCallState("speaking");
      const scheduleTime = Math.max(ctx.currentTime + 0.02, playbackStartTimeRef.current);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(playbackAnalyserRef.current);
      playbackSourcesRef.current.add(source);
      playbackStartTimeRef.current = scheduleTime + buffer.duration;
      playbackSourceRef.current = source;
      source.onended = () => {
        playbackSourcesRef.current.delete(source);
        if (playbackSourcesRef.current.size === 0) {
          playbackSourceRef.current = null;
          isPlayingAudioRef.current = false;
          setCallState("listening");
        }
      };
      source.start(scheduleTime);
    } catch (e) {
      console.warn("[Playback] Failed to decode audio chunk:", e);
    }
  });
}

// Stop speech immediately when the user starts talking and discard buffered audio.
function stopPlaybackForBargeIn() {
  playbackGenerationRef.current += 1;
  audioPlaybackQueue.current.length = 0;
  playbackDecodeChainRef.current = Promise.resolve();
  for (const source of playbackSourcesRef.current) {
    try { source.stop(); } catch (_) {}
    try { source.disconnect(); } catch (_) {}
  }
  playbackSourcesRef.current.clear();
  playbackSourceRef.current = null;
  playbackStartTimeRef.current = 0;
  isPlayingAudioRef.current = false;
}

// ── Start WebSocket Call (replaces old startListening) ──
const startCallSession = useCallback(async () => {
  if (!activeRef.current) return;

  setCallState("connecting");

  // 1. Get mic stream for raw PCM capture
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    micStreamRef.current = stream;

    // 2. Open WebSocket
    const wsUrl = API_URL.replace(/^http/, "ws") + "/api/voice/ws";
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    // Send partial transcript updates to state
    let assistantMsgId = null;

    ws.onopen = () => {
      setCallState("connecting");
      ws.send(JSON.stringify({
        type: "start_call",
        thread_id: threadIdRef.current,
      }));
      startAudioCapture(stream, ws);
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        // Binary audio chunk from TTS — play it
        playAudioChunk(event.data);
      } else {
        // JSON event
        try {
          const msg = JSON.parse(event.data);
          switch (msg.type) {
            case "voice_ready":
              setCallState("listening");
              break;

            case "voice_error":
              console.error("Voice service error:", msg.message);
              setConnectionError(msg.message || "Unable to connect to the voice service.");
              setCallState("error");
              activeRef.current = false;
              clearTimeout(inactivityTimerRef.current);
              if (micStreamRef.current) {
                micStreamRef.current.getTracks().forEach((track) => track.stop());
                micStreamRef.current = null;
              }
              break;

            case "partial_transcript":
              // Optionally show partial transcript in UI
              break;

            case "transcript":
              // Final transcript — add user message
              // Also store detected language for TTS
              if (msg.language_code) {
                detectedLanguageRef.current = msg.language_code;
              }
              const userMsgId = crypto.randomUUID();
              setCallMessages((prev) => [
                ...prev,
                { id: userMsgId, role: "user", text: msg.text },
              ]);
              // Create placeholder for assistant
              assistantMsgId = crypto.randomUUID();
              setCallMessages((prev) => [
                ...prev,
                { id: assistantMsgId, role: "assistant", text: "" },
              ]);
              setCallState("thinking");
              break;

            case "agent_token":
              if (assistantMsgId) {
                setCallMessages((prev) => prev.map((message) =>
                  message.id === assistantMsgId
                    ? { ...message, text: message.text + (msg.content || "") }
                    : message
                ));
              }
              break;

            case "agent_done":
              if (assistantMsgId && msg.full_content) {
                setCallMessages((prev) => prev.map((message) =>
                  message.id === assistantMsgId && !message.text
                    ? { ...message, text: msg.full_content }
                    : message
                ));
              }
              break;

            case "vad_speech_start":
              stopPlaybackForBargeIn();
              setCallState("listening");
              break;

            case "vad_speech_end":
            case "speech_end":
              // Sarvam detected end of speech and is preparing the final transcript
              setCallState("processing");
              break;
          }
        } catch (e) {
          // ignore parse errors
        }
      }
    };

    ws.onclose = () => {
      if (activeRef.current) {
        handleEndCall();
      }
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
      handleEndCall();
    };

    // Set 60s total inactivity timeout (simpler than the old 30s prompt)
    clearTimeout(inactivityTimerRef.current);
    inactivityTimerRef.current = setTimeout(() => {
      if (activeRef.current) {
        handleInactivityPrompt();
      }
    }, 60000);

  } catch (err) {
    console.error("Mic access error:", err);
    handleEndCall();
  }
}, [handleInactivityPrompt]);
  // ── Initiate Call Session ──
  useEffect(() => {
    if (isOpen) {
      activeRef.current = true;
      threadIdRef.current = crypto.randomUUID();
      setTimeout(() => startCallSession(), 600);
    }
    return () => {
      activeRef.current = false;
      clearTimeout(inactivityTimerRef.current);
    };
  }, [isOpen, startCallSession]);

  // ── Terminate Call Session ──
  const handleEndCall = useCallback(() => {
    activeRef.current = false;
    setCallState("connecting");
    clearTimeout(inactivityTimerRef.current);

    // Close WebSocket
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "end_call" }));
      }
      wsRef.current.close();
      wsRef.current = null;
    }

    // Stop mic
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }

    // Stop audio playback & clear queue
    stopPlaybackForBargeIn();

    // Close Playback AudioContext (separate from mic capture context)
    if (playbackCtxRef.current) {
      playbackCtxRef.current.close();
      playbackCtxRef.current = null;
      playbackAnalyserRef.current = null;
    }

    // Close AudioContext
    if (audioCtxRef.current) {
      audioCtxRef.current.close();
      audioCtxRef.current = null;
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
        <div className="call-screen" role="dialog" aria-modal="true" aria-labelledby="call-title" data-state={callState}>
          <div className="call-top-bar">
            <div className="call-brand"><span className="call-brand-mark">S</span><span>SCOUT <span className="call-brand-secondary">/ VOICE</span></span></div>
            <div className="call-session"><span className="call-live-dot" /><span>{callState === "error" ? "Disconnected" : callState === "connecting" ? "Connecting" : "Live session"}</span><span className="call-duration">{formatDuration(callDuration)}</span></div>
          </div>

          <div className="call-main">
            <div className="call-header-center">
              <span className="call-eyebrow">A LITTLE CLOSER TO CAMPUS</span>
              <div className="call-orb-stage"><VoiceOrb state={callState} analyserRef={playbackAnalyserRef} /></div>
              <h2 className="call-name" id="call-title">{callState === "speaking" ? "Scout is speaking" : callState === "thinking" ? "Connecting the dots" : callState === "processing" ? "Got it. One moment." : callState === "error" ? "Connection interrupted" : callState === "connecting" ? "Meet your campus companion" : "I'm all ears."}</h2>
              <p className="call-subtitle">Your world at Thapar. One conversation away.</p>
              <div className="call-status-text" role="status">
                <span className="call-state-indicator" />
                {callState === "connecting" && "Setting up your call"}
                {callState === "error" && connectionError}
                {callState === "listening" && "Listening - speak freely"}
                {callState === "processing" && "Transcribing your words"}
                {callState === "thinking" && "Finding your answer"}
                {callState === "speaking" && "Speaking - you can interrupt anytime"}
              </div>
            </div>

            <section className="call-transcript" aria-label="Call transcript">
              <div className="call-transcript-heading"><span>Conversation</span><span className="call-transcript-tag">LIVE TRANSCRIPT</span></div>
          {/* Scrollable Conversation History (Kept visible all through call) */}
          <div className="call-conversation-list">
            {callMessages.length === 0 ? (
              <div className="call-history-empty">
                <span className="call-empty-symbol" aria-hidden="true">✳</span>
                <h3>Good conversations start here.</h3>
                <p>Ask about admissions, campus life, or what comes next. Your conversation will appear here as you talk.</p>
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

            </section>
          </div>

          {/* End Call Button */}
          <div className="call-bottom-action">
            <span className="call-footer-note">TIET College Assistant</span>
            <div className="call-end-control">
            <motion.button
              className="call-end-btn"
              onClick={handleEndCall}
              aria-label="End call"
              whileHover={{ scale: 1.06 }}
              whileTap={{ scale: 0.94 }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91" />
                <line x1="23" y1="1" x2="1" y2="23" />
              </svg>
            </motion.button>
            <span className="call-end-label">End call</span>
            </div>
            <span className="call-footer-note call-footer-hint">Just talk. Scout is here.</span>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
