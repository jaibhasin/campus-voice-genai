"use client";

import { useRef, useState, useCallback, useEffect } from "react";

/**
 * useVoiceCall — Hands-free voice conversation with Scout.
 *
 * State machine:
 *   IDLE → LISTENING → PROCESSING_STT → WAITING_AGENT → PLAYING_TTS → LISTENING (loop)
 *
 * @param {Function} onSend       - sends text as a user message (same as typing + enter)
 * @param {boolean}  isStreaming   - true while the agent is streaming a response
 * @param {string}   lastBotMessage - the full text of the last completed bot message
 * @param {string}   apiUrl       - backend base URL
 */
export default function useVoiceCall({ onSend, isStreaming, lastBotMessage, apiUrl }) {
  const [callState, setCallState] = useState("idle");
  // "idle" | "listening" | "processing" | "responding" | "speaking"

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const analyserRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const audioRef = useRef(null);
  const isInCallRef = useRef(false);

  const isInCall = callState !== "idle";

  // ── Silence Detection ──
  // Monitors mic volume; when it drops below threshold for 1.5s, stops recording
  const startSilenceDetection = useCallback((stream) => {
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyserRef.current = { analyser, audioCtx };

    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    let silenceStart = null;
    const SILENCE_THRESHOLD = 15;
    const SILENCE_DURATION = 1500; // ms

    const check = () => {
      if (!isInCallRef.current) return;

      analyser.getByteFrequencyData(dataArray);
      const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

      if (avg < SILENCE_THRESHOLD) {
        if (!silenceStart) silenceStart = Date.now();
        else if (Date.now() - silenceStart > SILENCE_DURATION) {
          // User stopped speaking → stop recording
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

    // Delay start to skip initial noise
    setTimeout(() => requestAnimationFrame(check), 500);
  }, []);

  // ── Start Listening ──
  const startListening = useCallback(async () => {
    if (!isInCallRef.current) return;

    setCallState("listening");
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm",
      });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        if (!isInCallRef.current) return;

        const blob = new Blob(chunksRef.current, { type: "audio/webm" });

        // Skip if too small (< 1KB = probably silence/noise)
        if (blob.size < 1000) {
          if (isInCallRef.current) startListening();
          return;
        }

        // Send to STT
        setCallState("processing");
        try {
          const formData = new FormData();
          formData.append("file", blob, "recording.webm");

          const resp = await fetch(`${apiUrl}/api/stt`, {
            method: "POST",
            body: formData,
          });
          const data = await resp.json();

          if (data.transcript && data.transcript.trim()) {
            setCallState("responding");
            onSend(data.transcript.trim());
          } else {
            // No speech detected, resume listening
            if (isInCallRef.current) startListening();
          }
        } catch (err) {
          console.error("STT error:", err);
          if (isInCallRef.current) startListening();
        }
      };

      recorder.start();
      startSilenceDetection(stream);
    } catch (err) {
      console.error("Mic access error:", err);
      setCallState("idle");
      isInCallRef.current = false;
    }
  }, [apiUrl, onSend, startSilenceDetection]);

  // ── Play TTS and resume listening ──
  const playTTS = useCallback(
    async (text) => {
      if (!isInCallRef.current || !text) {
        if (isInCallRef.current) startListening();
        return;
      }

      setCallState("speaking");

      try {
        const resp = await fetch(`${apiUrl}/api/tts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, language_code: "en-IN" }),
        });
        const data = await resp.json();

        if (data.audio_base64) {
          // Decode base64 to audio
          const audioSrc = `data:audio/wav;base64,${data.audio_base64}`;
          const audio = new Audio(audioSrc);
          audioRef.current = audio;

          audio.onended = () => {
            if (isInCallRef.current) startListening();
          };
          audio.onerror = () => {
            if (isInCallRef.current) startListening();
          };

          await audio.play();
        } else {
          // TTS failed, resume listening anyway
          if (isInCallRef.current) startListening();
        }
      } catch (err) {
        console.error("TTS error:", err);
        if (isInCallRef.current) startListening();
      }
    },
    [apiUrl, startListening]
  );

  // ── Watch for agent response completion → trigger TTS ──
  const prevStreamingRef = useRef(isStreaming);
  useEffect(() => {
    // Detect transition: isStreaming went from true → false
    if (prevStreamingRef.current && !isStreaming && callState === "responding") {
      // Agent finished streaming — play TTS
      if (lastBotMessage && isInCallRef.current) {
        playTTS(lastBotMessage);
      }
    }
    prevStreamingRef.current = isStreaming;
  }, [isStreaming, callState, lastBotMessage, playTTS]);

  // ── Start Call ──
  const startCall = useCallback(() => {
    isInCallRef.current = true;
    startListening();
  }, [startListening]);

  // ── End Call ──
  const endCall = useCallback(() => {
    isInCallRef.current = false;
    setCallState("idle");

    // Stop recording
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }

    // Stop mic stream
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    // Stop audio playback
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    // Clean up analyser
    if (analyserRef.current?.audioCtx) {
      analyserRef.current.audioCtx.close();
      analyserRef.current = null;
    }

    clearTimeout(silenceTimerRef.current);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (isInCallRef.current) endCall();
    };
  }, [endCall]);

  return {
    callState,
    startCall,
    endCall,
    isInCall,
  };
}
