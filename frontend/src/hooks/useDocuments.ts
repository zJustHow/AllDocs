import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { deleteDocument, listDocuments, reindexDocument, uploadDocument } from "../api";
import { loadSupportedFormats } from "../fileTypes";
import { useI18n } from "../i18n";
import type { DocumentItem } from "../types";
import type { ConfirmOptions } from "../useConfirmDialog";

interface UseDocumentsOptions {
  setError: Dispatch<SetStateAction<string | null>>;
  confirm: (options: ConfirmOptions | string) => Promise<boolean>;
}

export function useDocuments({ setError, confirm }: UseDocumentsOptions) {
  const { t } = useI18n();
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const userModifiedSelectionRef = useRef(false);

  const statusLabel = useMemo(
    (): Record<DocumentItem["status"], string> => ({
      pending: t("doc.status.pending"),
      processing: t("doc.status.processing"),
      ready: t("doc.status.ready"),
      failed: t("doc.status.failed"),
      deleting: t("doc.status.deleting"),
    }),
    [t],
  );

  const readyDocs = useMemo(
    () => documents.filter((doc) => doc.status === "ready"),
    [documents],
  );

  const indexingDocs = useMemo(
    () =>
      documents.filter(
        (doc) =>
          doc.status === "pending" ||
          doc.status === "processing" ||
          doc.status === "deleting",
      ),
    [documents],
  );

  const refreshDocuments = useCallback(async () => {
    const docs = await listDocuments();
    setDocuments(docs);
    setSelectedDocIds((prev) => {
      const readyIds = docs
        .filter((d) => d.status === "ready")
        .map((d) => d.id);
      if (prev.length === 0 && !userModifiedSelectionRef.current) {
        return readyIds;
      }
      return prev.filter((id) => readyIds.includes(id));
    });
  }, []);

  useEffect(() => {
    void loadSupportedFormats();
    refreshDocuments().catch((err) => setError(String(err)));

    const intervalMs = indexingDocs.length > 0 ? 500 : 5000;
    let timer: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (timer) return;
      timer = setInterval(() => {
        if (document.visibilityState !== "visible") return;
        refreshDocuments().catch(() => undefined);
      }, intervalMs);
    };

    const stopPolling = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refreshDocuments().catch(() => undefined);
        startPolling();
      } else {
        stopPolling();
      }
    };

    if (document.visibilityState === "visible") {
      startPolling();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refreshDocuments, indexingDocs.length, setError]);

  const toggleDoc = useCallback((docId: string) => {
    userModifiedSelectionRef.current = true;
    setSelectedDocIds((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId],
    );
  }, []);

  const handleUpload = useCallback(
    async (file: File | null) => {
      if (!file) return;
      setUploading(true);
      setError(null);
      try {
        await uploadDocument(file);
        await refreshDocuments();
      } catch (err) {
        setError(String(err));
      } finally {
        setUploading(false);
      }
    },
    [refreshDocuments, setError],
  );

  const handleDelete = useCallback(
    async (docId: string) => {
      const confirmed = await confirm({
        title: t("sidebar.deleteDoc"),
        message: t("sidebar.deleteConfirm"),
        confirmLabel: t("sidebar.deleteDoc"),
        variant: "danger",
      });
      if (!confirmed) return;
      setSelectedDocIds((prev) => prev.filter((id) => id !== docId));
      await deleteDocument(docId);
      await refreshDocuments();
    },
    [confirm, refreshDocuments, t],
  );

  const handleReindex = useCallback(
    async (docId: string) => {
      const confirmed = await confirm({
        title: t("sidebar.reindexDoc"),
        message: t("sidebar.reindexConfirm"),
        confirmLabel: t("sidebar.reindexDoc"),
      });
      if (!confirmed) return;
      setError(null);
      try {
        await reindexDocument(docId);
        await refreshDocuments();
      } catch (err) {
        setError(String(err));
      }
    },
    [confirm, refreshDocuments, setError, t],
  );

  return {
    documents,
    selectedDocIds,
    readyDocs,
    indexingDocs,
    statusLabel,
    uploading,
    toggleDoc,
    handleUpload,
    handleDelete,
    handleReindex,
  };
}
