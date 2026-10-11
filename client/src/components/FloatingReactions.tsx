import { useEffect, useState } from "react";
import type { Participant } from "../lib/types";

type ReactionEvent = { userId: string; emoji: string };

type Floater = { id: number; emoji: string; userId: string; x: number };

const LIFETIME_MS = 2400;

/**
 * Reactions float up over the video and fade out.
 *
 * The server sends only {userId, emoji} (handlers/chat.py:79), so the name is
 * resolved from the roster at render time; a reaction from someone who has
 * already left still animates, just without a name.
 */
export default function FloatingReactions({
  current,
  participants,
}: {
  current: ReactionEvent | null;
  participants: Participant[];
}) {
  const [floaters, setFloaters] = useState<Floater[]>([]);

  useEffect(() => {
    if (!current) {
      return;
    }
    const id = Date.now() + Math.random();
    const x = 12 + Math.random() * 76;
    setFloaters((prev) => [...prev.slice(-5), { id, emoji: current.emoji, userId: current.userId, x }]);
    const timer = window.setTimeout(() => {
      setFloaters((prev) => prev.filter((item) => item.id !== id));
    }, LIFETIME_MS);
    return () => window.clearTimeout(timer);
  }, [current]);

  if (floaters.length === 0) {
    return null;
  }

  const names = new Map(participants.map((p) => [p.userId, p.username]));

  return (
    <div className="floating" aria-hidden data-testid="floating-reactions">
      {floaters.map((item) => (
        <span
          key={item.id}
          className="reaction-float"
          style={{ left: `${item.x}%` }}
          title={names.get(item.userId)}
        >
          {item.emoji}
        </span>
      ))}
    </div>
  );
}