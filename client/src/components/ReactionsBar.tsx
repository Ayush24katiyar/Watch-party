import { ALLOWED_EMOJI, type Reaction } from "../lib/types";

/** Reaction bar: the 8 allowed emoji, available to everyone in the room. */
export default function ReactionsBar({
  onReact,
  disabled,
}: {
  onReact: (emoji: Reaction) => void;
  disabled: boolean;
}) {
  return (
    <div className="reactions" role="group" aria-label="Send a reaction" data-testid="reactions-bar">
      {ALLOWED_EMOJI.map((emoji) => (
        <button
          key={emoji}
          type="button"
          className="reaction-btn"
          aria-label={`React with ${emoji}`}
          disabled={disabled}
          onClick={() => onReact(emoji)}
        >
          {emoji}
        </button>
      ))}
    </div>
  );
}