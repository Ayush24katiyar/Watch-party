/** YouTube URL parsing (architecture 11) and IFrame API loader. */

/** Extract a video ID from watch URLs, share URLs, shorts, embeds, or a bare ID. */
export function parseVideoId(input: string): string | null {
  const trimmed = input.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(trimmed)) {
    return trimmed;
  }
  try {
    const url = new URL(trimmed);
    if (url.hostname.includes("youtu.be")) {
      const id = url.pathname.slice(1).split("/")[0];
      return /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
    }
    if (url.hostname.includes("youtube.com")) {
      if (url.pathname === "/watch") {
        const id = url.searchParams.get("v");
        return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
      }
      const match = url.pathname.match(/^\/(embed|shorts)\/([A-Za-z0-9_-]{11})/);
      return match ? match[2] : null;
    }
    return null;
  } catch {
    return null;
  }
}

declare global {
  interface Window {
    YT?: {
      Player: new (
        element: HTMLElement | string,
        config: Record<string, unknown>,
      ) => {
        playVideo: () => void;
        pauseVideo: () => void;
        seekTo: (seconds: number, allowSeekAhead: boolean) => void;
        getCurrentTime: () => number;
        getPlayerState: () => number;
        destroy: () => void;
      };
      PlayerState: {
        UNSTARTED: number;
        ENDED: number;
        PLAYING: number;
        PAUSED: number;
        BUFFERING: number;
        CUED: number;
      };
    };
    onYouTubeIframeAPIReady?: () => void;
  }
}

let apiPromise: Promise<void> | null = null;

/** Load the YouTube IFrame API exactly once. */
export function loadYouTubeApi(): Promise<void> {
  if (apiPromise) {
    return apiPromise;
  }
  apiPromise = new Promise((resolve) => {
    if (window.YT?.Player) {
      resolve();
      return;
    }
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      resolve();
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    document.body.appendChild(script);
  });
  return apiPromise;
}
