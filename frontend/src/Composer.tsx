import { memo, type RefObject } from "react";
import { useI18n } from "./i18n";
import { MicIcon, SendIcon } from "./icons";

interface ComposerProps {
  input: string;
  loading: boolean;
  recording: boolean;
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
  textareaRef,
  onInputChange,
  onSend,
  onStartRecording,
  onStopRecording,
}: ComposerProps) {
  const { t } = useI18n();

  return (
    <footer className="composer-wrap">
      <div className="input-pill">
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
      <p className="composer-disclaimer">{t("app.disclaimer")}</p>
    </footer>
  );
}

export default memo(Composer);
