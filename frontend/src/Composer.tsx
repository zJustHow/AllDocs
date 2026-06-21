import { memo, useLayoutEffect, useRef, type RefObject } from "react";
import { useI18n } from "./i18n";
import { MicIcon, SendIcon } from "./icons";

interface ComposerProps {
  input: string;
  loading: boolean;
  recording: boolean;
  voiceStatus?: string | null;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
}

function Composer({
  input,
  loading,
  recording,
  voiceStatus,
  textareaRef,
  onInputChange,
  onSend,
  onStartRecording,
  onStopRecording,
}: ComposerProps) {
  const { t } = useI18n();
  const inputPillRef = useRef<HTMLDivElement>(null);
  const bottomMaskRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const inputPill = inputPillRef.current;
    const bottomMask = bottomMaskRef.current;
    if (!inputPill || !bottomMask) return;

    const syncMaskOverlap = () => {
      const inputHeight = inputPill.getBoundingClientRect().height;
      if (inputHeight > 0) {
        bottomMask.style.setProperty(
          "--composer-mask-overlap",
          `${inputHeight / 2}px`,
        );
      }
    };

    syncMaskOverlap();
    const observer = new ResizeObserver(syncMaskOverlap);
    observer.observe(inputPill);
    return () => observer.disconnect();
  }, []);

  return (
    <footer className="main-footer">
      <div className="composer-wrap">
        <div ref={inputPillRef} className="input-pill">
          <textarea
            ref={textareaRef}
            value={input}
            placeholder={t("chat.placeholder")}
            rows={1}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
          />
          <div className="input-actions">
            <button
              className={`action-btn mic ${recording ? "active" : ""}`}
              onClick={recording ? onStopRecording : onStartRecording}
              disabled={loading && !recording}
              title={t("voice.ask")}
              aria-label={
                recording ? t("voice.stopRecording") : t("voice.ask")
              }
            >
              <MicIcon />
            </button>
            <button
              className="action-btn send"
              onClick={onSend}
              disabled={loading || !input.trim()}
              title={t("composer.send")}
              aria-label={t("composer.send")}
            >
              <SendIcon />
            </button>
          </div>
        </div>
      </div>
      <div ref={bottomMaskRef} className="composer-bottom-mask">
        <p className={`composer-disclaimer${voiceStatus ? " voice-status" : ""}`}>
          {voiceStatus ?? t("app.disclaimer")}
        </p>
      </div>
    </footer>
  );
}

export default memo(Composer);
