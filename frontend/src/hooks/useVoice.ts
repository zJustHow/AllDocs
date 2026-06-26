import {
  useCallback,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { createVoiceSocket } from "../api";
import { createAssistantStreamController } from "../chatStream";
import { useI18n } from "../i18n";
import type { ChatMessage } from "../types";
import { newId } from "../utils/newId";

const RECORDING_MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

const MIN_RECORDING_BYTES = 512;

function pickRecordingMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  for (const mime of RECORDING_MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime;
  }
  return "audio/webm";
}

function mapVoiceStage(stage: string, t: (key: string) => string): string {
  switch (stage) {
    case "model_loading":
      return t("voice.modelLoading");
    case "transcribing":
      return t("voice.transcribing");
    case "retrieving":
      return t("voice.retrieving");
    case "answering":
      return t("voice.generating");
    case "speaking":
      return t("voice.synthesizing");
    default:
      return t("voice.connecting");
  }
}

interface UseVoiceOptions {
  selectedDocIds: string[];
  sessionId: string | null;
  loading: boolean;
  isAdmin: boolean;
  readyDocCount: number;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setSessionId: (sessionId: string) => void;
  setLoading: (loading: boolean) => void;
  setScrollTargetId: (id: string | null) => void;
  setError: Dispatch<SetStateAction<string | null>>;
}

export function useVoice({
  selectedDocIds,
  sessionId,
  loading,
  isAdmin,
  readyDocCount,
  setMessages,
  setSessionId,
  setLoading,
  setScrollTargetId,
  setError,
}: UseVoiceOptions) {
  const { t, locale } = useI18n();
  const [recording, setRecording] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingMimeRef = useRef("audio/webm");
  const audioQueueRef = useRef<HTMLAudioElement[]>([]);
  const playingRef = useRef(false);
  const voiceDoneRef = useRef(false);

  const playNextAudio = useCallback(() => {
    if (playingRef.current) return;
    const next = audioQueueRef.current.shift();
    if (!next) return;
    playingRef.current = true;
    setVoiceStatus(t("voice.playing"));
    next.onended = () => {
      playingRef.current = false;
      playNextAudio();
    };
    next.play().catch(() => {
      playingRef.current = false;
      playNextAudio();
    });
  }, [t]);

  const enqueueAudio = useCallback(
    (base64: string) => {
      const audio = new Audio(`data:audio/wav;base64,${base64}`);
      audioQueueRef.current.push(audio);
      playNextAudio();
    },
    [playNextAudio],
  );

  const finishVoice = useCallback(
    (message?: string) => {
      if (voiceDoneRef.current) return;
      voiceDoneRef.current = true;
      setVoiceStatus(null);
      if (message) setError(message);
      setLoading(false);
    },
    [setError, setLoading],
  );

  const sendVoice = useCallback(
    async (blob: Blob, mimeType: string) => {
      if (readyDocCount === 0) {
        setError(t(isAdmin ? "chat.selectDocError" : "chat.noDocsError"));
        return;
      }

      setLoading(true);
      setError(null);
      setVoiceStatus(t("voice.connecting"));
      audioQueueRef.current = [];
      voiceDoneRef.current = false;

      let ws: WebSocket | null = null;
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      let stream: ReturnType<typeof createAssistantStreamController> | null =
        null;

      const cleanup = (message?: string) => {
        stream?.flush();
        if (timeoutId) clearTimeout(timeoutId);
        if (ws && ws.readyState === WebSocket.OPEN) ws.close();
        finishVoice(message);
      };

      try {
        const reader = new FileReader();
        const base64 = await new Promise<string>((resolve, reject) => {
          reader.onload = () => {
            const result = reader.result as string;
            resolve(result.split(",")[1] ?? "");
          };
          reader.onerror = () => reject(reader.error);
          reader.readAsDataURL(blob);
        });

        ws = createVoiceSocket();
        const assistantId = newId();
        stream = createAssistantStreamController({
          assistantId,
          setMessages,
          setSessionId,
          setError,
          setLoading,
          onAudio: enqueueAudio,
        });

        timeoutId = setTimeout(() => {
          cleanup(t("voice.timeout"));
        }, 300_000);

        const opened = new Promise<void>((resolve, reject) => {
          ws!.onopen = () => resolve();
          ws!.onerror = () => {
            const error = new Error(t("voice.connectionFailed"));
            cleanup(error.message);
            reject(error);
          };
        });

        ws.onmessage = (event) => {
          let payload: { type: string; [key: string]: unknown };
          try {
            payload = JSON.parse(event.data);
          } catch {
            cleanup(t("voice.parseFailed"));
            return;
          }

          if (payload.type === "status") {
            setVoiceStatus(
              mapVoiceStage(String(payload.stage ?? ""), t),
            );
            return;
          }

          if (payload.type === "transcript") {
            const userMessageId = newId();
            setScrollTargetId(userMessageId);
            setVoiceStatus(t("voice.retrieving"));
            setMessages((prev) => [
              ...prev,
              {
                id: userMessageId,
                role: "user",
                content: payload.text as string,
              },
              {
                id: assistantId,
                role: "assistant",
                content: "",
                streaming: true,
                citations: [],
                agentSteps: [],
                agentRunning: true,
              },
            ]);
            return;
          }

          if (
            payload.type === "agent_step" ||
            payload.type === "agent_step_start"
          ) {
            setVoiceStatus(t("chat.agentRunning"));
          }

          const result = stream?.dispatchPayload(payload) ?? "continue";
          if (result === "done") {
            cleanup();
            return;
          }
          if (result === "error") {
            cleanup(payload.message as string);
          }
        };

        ws.onclose = () => {
          if (!voiceDoneRef.current) {
            cleanup(t("voice.disconnected"));
          }
        };

        await opened;
        ws.send(
          JSON.stringify({
            type: "audio",
            data: base64,
            mime_type: mimeType,
            language: locale === "zh" ? "zh" : "en",
            session_id: sessionId,
            doc_ids: selectedDocIds,
            with_audio: true,
          }),
        );
      } catch (err) {
        cleanup(String(err));
      }
    },
    [
      enqueueAudio,
      finishVoice,
      locale,
      selectedDocIds,
      sessionId,
      isAdmin,
      readyDocCount,
      setError,
      setLoading,
      setMessages,
      setScrollTargetId,
      setSessionId,
      t,
    ],
  );

  const startRecording = useCallback(async () => {
    if (loading || recording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const mimeType = pickRecordingMimeType();
      recordingMimeRef.current = mimeType;
      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined,
      );
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
        const type =
          recorder.mimeType || recordingMimeRef.current || "audio/webm";
        const blob = new Blob(audioChunksRef.current, { type });
        if (blob.size < MIN_RECORDING_BYTES) {
          setError(t("voice.noAudio"));
          return;
        }
        await sendVoice(blob, type);
      };
      mediaRecorderRef.current = recorder;
      recorder.start(250);
      setRecording(true);
      setVoiceStatus(t("voice.recording"));
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, [loading, recording, sendVoice, setError, t]);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.requestData();
    recorder.stop();
    mediaRecorderRef.current = null;
    setRecording(false);
    setVoiceStatus(t("voice.connecting"));
  }, [t]);

  return {
    recording,
    voiceStatus,
    startRecording,
    stopRecording,
  };
}
