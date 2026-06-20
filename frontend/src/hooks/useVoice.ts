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

interface UseVoiceOptions {
  selectedDocIds: string[];
  sessionId: string | null;
  loading: boolean;
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
  setMessages,
  setSessionId,
  setLoading,
  setScrollTargetId,
  setError,
}: UseVoiceOptions) {
  const { t } = useI18n();
  const [recording, setRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioQueueRef = useRef<HTMLAudioElement[]>([]);
  const playingRef = useRef(false);
  const voiceDoneRef = useRef(false);

  const playNextAudio = useCallback(() => {
    if (playingRef.current) return;
    const next = audioQueueRef.current.shift();
    if (!next) return;
    playingRef.current = true;
    next.onended = () => {
      playingRef.current = false;
      playNextAudio();
    };
    next.play().catch(() => {
      playingRef.current = false;
      playNextAudio();
    });
  }, []);

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
      if (message) setError(message);
      setLoading(false);
    },
    [setError, setLoading],
  );

  const sendVoice = useCallback(
    async (blob: Blob) => {
      if (selectedDocIds.length === 0) {
        setError(t("chat.selectDocError"));
        return;
      }

      setLoading(true);
      setError(null);
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

        ws.onopen = () => {
          ws?.send(
            JSON.stringify({
              type: "audio",
              data: base64,
              session_id: sessionId,
              doc_ids: selectedDocIds,
              with_audio: true,
            }),
          );
        };

        ws.onmessage = (event) => {
          let payload: { type: string; [key: string]: unknown };
          try {
            payload = JSON.parse(event.data);
          } catch {
            cleanup(t("voice.parseFailed"));
            return;
          }

          if (payload.type === "transcript") {
            const userMessageId = newId();
            setScrollTargetId(userMessageId);
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

          const result = stream?.dispatchPayload(payload) ?? "continue";
          if (result === "done") {
            cleanup();
            return;
          }
          if (result === "error") {
            cleanup(payload.message as string);
          }
        };

        ws.onerror = () => {
          cleanup(t("voice.connectionFailed"));
        };

        ws.onclose = () => {
          if (!voiceDoneRef.current) {
            cleanup(t("voice.disconnected"));
          }
        };
      } catch (err) {
        cleanup(String(err));
      }
    },
    [
      enqueueAudio,
      finishVoice,
      selectedDocIds,
      sessionId,
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
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        await sendVoice(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (err) {
      setError(String(err));
    }
  }, [loading, recording, sendVoice, setError]);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.requestData();
    recorder.stop();
    setRecording(false);
  }, []);

  return {
    recording,
    startRecording,
    stopRecording,
  };
}
