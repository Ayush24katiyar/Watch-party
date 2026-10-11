import { useState } from "react";

type ChatMessage = {
  userId: string;
  username: string;
  text: string;
  createdAt: string;
};

/** Chat panel: recent history + live messages + composer (Phase 7, 8.3). */
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

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (text) {
      onSend(text);
      setDraft("");
    }
  };

  return (
    <section className="chat-panel" data-testid="chat-panel">
      <h2>Chat</h2>
      <ul className="chat-messages">
        {messages.map((message, index) => (
          <li key={`${message.createdAt}-${index}`} data-testid="chat-message">
            <strong>{message.userId === youId ? `${message.username} (you)` : message.username}:</strong>{" "}
            {message.text}
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="chat-form">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Say something..."
          maxLength={500}
          aria-label="Chat message"
        />
        <button type="submit">Send</button>
      </form>
    </section>
  );
}
