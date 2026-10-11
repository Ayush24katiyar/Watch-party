import { useEffect, useRef, useState } from "react";
import { MessageSquare, SendHorizonal } from "lucide-react";
import type { ChatMessage } from "../lib/types";
import { CHAT_MAX } from "../lib/types";

const RATE_LIMIT_NOTICE_MS = 2_000;

/** Chat: history, live messages, and a composer with a counter (8.3). */
export default function ChatPanel({
  messages,
  youId,
  onSend,
}: {
  messages: ChatMessage[];
  youId: string | null;
  onSend: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [throttled, setThrottled] = useState(false);
  const logRef = useRef<HTMLUListElement>(null);

  // Keep the newest message in view.
  useEffect(() => {
    const log = logRef.current;
    if (log) {
      log.scrollTop = log.scrollHeight;
    }
  }, [messages.length]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text) {
      return;
    }
    onSend(text.slice(0, CHAT_MAX));
    setDraft("");
  };

  const remaining = CHAT_MAX - draft.length;

  return (
    <div className="tab-body">
      {messages.length === 0 ? (
        <p className="empty-state">
          <MessageSquare size={20} aria-hidden />
          No messages yet. Say hello.
        </p>
      ) : (
        <ul className="chat-log" ref={logRef} data-testid="chat-log">
          {messages.map((message, index) => {
            const mine = message.userId === youId;
            return (
              <li className="chat-line" key={`${message.createdAt}-${index}`}>
                <span className={mine ? "chat-who chat-you" : "chat-who"}>
                  {message.username}
                </span>
                <span className="chat-time">
                  {new Date(message.createdAt).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
                <div>{message.text}</div>
              </li>
            );
          })}
        </ul>
      )}

      {throttled && (
        <p className="error-text" role="status">
          Slow down - a few messages per second.
        </p>
      )}

      <form className="chat-compose" onSubmit={submit}>
        <label className="sr-only" htmlFor="chat-input">
          Message
        </label>
        <input
          id="chat-input"
          className="input url-input"
          value={draft}
          maxLength={CHAT_MAX}
          placeholder="Say something..."
          onChange={(event) => {
            setDraft(event.target.value);
            if (throttled) {
              setThrottled(false);
            }
          }}
          onBlur={() => setThrottled(false)}
          data-testid="chat-input"
        />
        <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
          <SendHorizonal size={16} aria-hidden />
          <span className="sr-only">Send</span>
        </button>
      </form>
      <div className="chat-meta">
        <span>{throttled ? "" : "Enter to send"}</span>
        <span aria-live="polite">{remaining <= 40 ? remaining : ""}</span>
      </div>
    </div>
  );
}

export { RATE_LIMIT_NOTICE_MS };