import { useRef, type PointerEvent, type ReactNode } from 'react';

type SwipeBackProps = {
  onBack: () => void;
  children: ReactNode;
};

export default function SwipeBack({ onBack, children }: SwipeBackProps) {
  const start = useRef<{ x: number; y: number } | null>(null);

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest('input, textarea, button, a, select, label')) return;
    start.current = { x: event.clientX, y: event.clientY };
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>) {
    const origin = start.current;
    start.current = null;
    if (!origin) return;
    const dx = event.clientX - origin.x;
    const dy = event.clientY - origin.y;
    if (dx > 72 && Math.abs(dx) > Math.abs(dy) * 1.4) onBack();
  }

  return (
    <div onPointerDown={handlePointerDown} onPointerUp={handlePointerUp} onPointerCancel={() => { start.current = null; }}>
      {children}
    </div>
  );
}
