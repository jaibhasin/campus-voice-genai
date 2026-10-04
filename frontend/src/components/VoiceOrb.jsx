"use client";

import { useEffect, useRef } from "react";

// Draw outside React's render loop so audio can animate without rerendering the call.
export default function VoiceOrb({ state, analyserRef }) {
  const canvasRef = useRef(null);
  const stateRef = useRef(state);
  const pointerRef = useRef({ x: 0, y: 0 });
  useEffect(() => { stateRef.current = state; }, [state]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const samples = new Uint8Array(256);
    const stars = Array.from({ length: 100 }, () => ({
      x: Math.random() - 0.5, y: Math.random() - 0.5,
      size: Math.random() * 1.2 + 0.2, phase: Math.random() * Math.PI * 2,
    }));
    const points = Array.from({ length: 650 }, (_, i) => {
      const y = 1 - (i / 649) * 2;
      const r = Math.sqrt(1 - y * y);
      const angle = i * Math.PI * (3 - Math.sqrt(5));
      return { x: Math.cos(angle) * r, y, z: Math.sin(angle) * r, phase: Math.random() * Math.PI * 2 };
    });
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
      const radius = size * (0.27 + energy * 0.025);
      ctx.clearRect(0, 0, size, size);
      ctx.save();
      ctx.translate(size / 2, size / 2);
      for (const star of stars) {
        const shimmer = reducedMotion.matches ? 0.5 : (Math.sin(time * 0.4 + star.phase) + 1) / 2;
        ctx.fillStyle = `rgba(255,255,255,${0.12 + shimmer * 0.35})`;
        ctx.beginPath();
        ctx.arc(star.x * size * 0.95, star.y * size * 0.95, star.size, 0, Math.PI * 2);
        ctx.fill();
      }
      const glow = ctx.createRadialGradient(0, 0, radius * 0.8, 0, 0, radius * 1.6);
      glow.addColorStop(0, `rgba(255,255,255,${0.12 + energy * 0.12})`);
      glow.addColorStop(0.3, "rgba(220,225,230,0.045)");
      glow.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(-size / 2, -size / 2, size, size);

      // A shaded core gives the constellation depth, like a small dark planet.
      const core = ctx.createRadialGradient(-radius * 0.35, -radius * 0.45, 0, 0, 0, radius);
      core.addColorStop(0, "#303236");
      core.addColorStop(0.5, "#111214");
      core.addColorStop(1, "#030303");
      ctx.beginPath();
      ctx.arc(0, 0, radius * 0.96, 0, Math.PI * 2);
      ctx.fillStyle = core;
      ctx.fill();

      const tilt = reducedMotion.matches ? 0.3 : 0.3 + pointerRef.current.y * 0.2;
      const rotation = time * 0.28 + (reducedMotion.matches ? 0 : pointerRef.current.x * 0.18);
      for (const point of points) {
        const x = point.x * Math.cos(rotation) + point.z * Math.sin(rotation);
        const z = point.z * Math.cos(rotation) - point.x * Math.sin(rotation);
        const y = point.y * Math.cos(tilt) - z * Math.sin(tilt);
        const depth = point.y * Math.sin(tilt) + z * Math.cos(tilt);
        if (depth < -0.15) continue;
        const drift = reducedMotion.matches ? 0 : Math.sin(time * 1.4 + point.phase) * (0.008 + energy * 0.07);
        ctx.fillStyle = `rgba(245,246,248,${0.12 + Math.max(0, depth) * 0.65})`;
        ctx.beginPath();
        ctx.arc(x * radius * (0.95 + drift), y * radius * (0.95 + drift), 0.5 + Math.max(0, depth) * 0.7, 0, Math.PI * 2);
        ctx.fill();
      }

      // A white corona ripples with the voice, surrounded by tilted orbital trails.
      for (let ring = 0; ring < 12; ring++) {
        ctx.beginPath();
        for (let step = 0; step <= 180; step++) {
          const angle = step / 180 * Math.PI * 2;
          const wave = Math.sin(angle * 4 + time * 1.1 + ring * 0.3) * Math.cos(angle * 3 - time * 0.6);
          const r = radius * (0.98 + ring * 0.004 + wave * (0.009 + energy * 0.055));
          const x = Math.cos(angle) * r, y = Math.sin(angle) * r;
          if (step === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = `rgba(255,255,255,${0.12 + (11 - ring) * 0.035})`;
        ctx.lineWidth = ring === 0 ? 1.5 : 0.6;
        ctx.stroke();
      }
      ctx.save();
      ctx.rotate(-0.42);
      for (let orbit = 0; orbit < 5; orbit++) {
        ctx.beginPath();
        ctx.ellipse(0, 0, radius * (1.48 + orbit * 0.025), radius * (0.38 + orbit * 0.012), 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(235,238,242,${0.035 + orbit * 0.008})`;
        ctx.lineWidth = 0.7;
        ctx.stroke();
      }
      for (let i = 0; i < 28; i++) {
        const angle = i * 2.39996 + time * (0.2 + (i % 3) * 0.07);
        const r = radius * (1.48 + (i % 5) * 0.025);
        ctx.beginPath();
        ctx.ellipse(0, 0, r, radius * 0.41, 0, angle, angle + 0.025 + energy * 0.05);
        ctx.strokeStyle = `rgba(255,255,255,${0.3 + (i % 4) * 0.15})`;
        ctx.lineWidth = i % 4 === 0 ? 1.8 : 1;
        ctx.stroke();
      }
      ctx.restore();
      ctx.restore();
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [analyserRef]);

  return <canvas
    ref={canvasRef}
    className="call-orb"
    aria-hidden="true"
    onPointerMove={(event) => {
      const bounds = event.currentTarget.getBoundingClientRect();
      pointerRef.current = { x: (event.clientX - bounds.left) / bounds.width - 0.5, y: (event.clientY - bounds.top) / bounds.height - 0.5 };
    }}
    onPointerLeave={() => { pointerRef.current = { x: 0, y: 0 }; }}
  />;
}
