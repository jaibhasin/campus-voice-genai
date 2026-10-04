"use client";

import { useEffect, useRef } from "react";

// Draw outside React's render loop so audio can animate without rerendering the call.
export default function VoiceOrb({ state, analyserRef }) {
  const canvasRef = useRef(null);
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const samples = new Uint8Array(256);
    const particles = Array.from({ length: 90 }, () => ({
      angle: Math.random() * Math.PI * 2,
      orbit: 0.72 + Math.random() * 0.65,
      speed: 0.15 + Math.random() * 0.45,
      size: 0.5 + Math.random() * 1.3,
      phase: Math.random() * Math.PI * 2,
    }));
    let size = 0;
    let frame;
    let energy = 0;
    let previousTime = 0;
    let time = 0;
    const resize = () => {
      size = canvas.clientWidth;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = size * dpr;
      canvas.height = size * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();

    const draw = (now) => {
      const speaking = stateRef.current === "speaking";
      const busy = ["thinking", "processing"].includes(stateRef.current);
      let volume = 0;
      if (speaking && analyserRef.current) {
        analyserRef.current.getByteTimeDomainData(samples);
        volume = Math.sqrt(samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0) / samples.length);
      }
      energy += ((reducedMotion.matches ? 0 : Math.min(volume * 5, 1)) - energy) * 0.16;
      const delta = previousTime ? Math.min((now - previousTime) / 1000, 0.05) : 0;
      previousTime = now;
      if (!reducedMotion.matches) time += delta * (speaking ? 1.6 + energy * 2 : busy ? 0.8 : 0.3);
      const radius = size * (0.275 + energy * 0.025);
      ctx.clearRect(0, 0, size, size);
      ctx.save();
      ctx.translate(size / 2, size / 2);

      const glow = ctx.createRadialGradient(0, 0, radius * 0.3, 0, 0, radius * 1.65);
      glow.addColorStop(0, `rgba(98, 126, 255, ${0.16 + energy * 0.14})`);
      glow.addColorStop(0.55, "rgba(110, 81, 236, 0.11)");
      glow.addColorStop(1, "rgba(90, 100, 255, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(-size / 2, -size / 2, size, size);

      // Interleaved fluid contours with independent phases create organic movement.
      for (let ring = 0; ring < 32; ring++) {
        const phase = ring * 0.17;
        ctx.beginPath();
        for (let step = 0; step <= 180; step++) {
          const angle = step / 180 * Math.PI * 2;
          const ripple = Math.sin(angle * 3 + time + phase) * Math.cos(angle * 2 - time * 0.7 + phase);
          const wave = Math.sin(angle * 5 - time * 1.3 + phase * 2);
          const r = radius * (0.83 + ring * 0.005 + ripple * (0.035 + energy * 0.12) + wave * (0.012 + energy * 0.035));
          const x = Math.cos(angle) * r;
          const y = Math.sin(angle) * r;
          if (step === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = `hsla(${185 + ring * 3.4}, 95%, ${66 + ring * 0.4}%, ${0.18 + ring / 95})`;
        ctx.lineWidth = ring % 5 === 0 ? 1.3 : 0.65;
        ctx.stroke();
      }
      for (const particle of particles) {
        const angle = particle.angle + time * particle.speed;
        const r = radius * (particle.orbit + Math.sin(time * 0.7 + particle.phase) * (0.035 + energy * 0.12));
        ctx.beginPath();
        ctx.arc(Math.cos(angle) * r, Math.sin(angle) * r, particle.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(177, 215, 255, ${0.3 + (Math.sin(time + particle.phase) + 1) * 0.25})`;
        ctx.fill();
      }
      ctx.restore();
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [analyserRef]);

  return <canvas ref={canvasRef} className="call-orb" aria-hidden="true" />;
}
