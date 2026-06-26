/** @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./SettingsPage";
import { I18nProvider } from "./i18n";

const fetchSettings = vi.fn();
const patchSettings = vi.fn();

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    fetchSettings: (...args: Parameters<typeof fetchSettings>) => fetchSettings(...args),
    patchSettings: (...args: Parameters<typeof patchSettings>) => patchSettings(...args),
  };
});

const samplePayload = {
  groups: [
    {
      id: "llm",
      fields: [
        {
          key: "llm_model",
          type: "string" as const,
          secret: false,
          default: "gpt-4",
          overridden: false,
          value: "gpt-4",
        },
        {
          key: "llm_api_key",
          type: "secret" as const,
          secret: true,
          default: "",
          overridden: true,
          value: null,
          set: true,
          masked: "sk-****",
        },
      ],
    },
  ],
};

function renderPage(isAdmin = true) {
  return render(
    <I18nProvider>
      <SettingsPage isAdmin={isAdmin} />
    </I18nProvider>,
  );
}

async function waitForAutoSave() {
  await waitFor(
    () => {
      expect(patchSettings).toHaveBeenCalled();
    },
    { timeout: 2000 },
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchSettings.mockResolvedValue(samplePayload);
    patchSettings.mockResolvedValue(samplePayload);
  });

  it("loads settings and renders fields on mount", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: /Management|管理/i })).toBeInTheDocument();
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(/模型|Model/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保存|Save/i })).not.toBeInTheDocument();
  });

  it("filters fields by search query", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    await user.type(screen.getByRole("searchbox"), "llm_api_key");

    expect(screen.getByLabelText(/API Key/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^模型$|^Model$/i)).not.toBeInTheDocument();
  });

  it("auto-saves dirty field changes", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const modelInput = screen.getByLabelText(/模型|Model/i);
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4.1");

    await waitForAutoSave();
    expect(patchSettings).toHaveBeenCalledWith({ llm_model: "gpt-4.1" });
    expect(await screen.findByText(/已保存|Settings saved/i)).toBeInTheDocument();
  });

  it("shows a load error when settings cannot be fetched", async () => {
    fetchSettings.mockRejectedValue(new Error("Settings unavailable"));
    renderPage();

    expect(await screen.findByText(/Settings unavailable/)).toBeInTheDocument();
  });

  it("shows a save error when patch settings fails", async () => {
    patchSettings.mockRejectedValue(new Error("Save rejected"));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const modelInput = screen.getByLabelText(/模型|Model/i);
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4.1");

    expect(await screen.findByText(/Save rejected/)).toBeInTheDocument();
  });

  it("auto-saves when resetting an overridden section back to defaults", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const llmGroup = screen
      .getByRole("button", { name: /^LLM$/i })
      .closest(".settings-group") as HTMLElement;
    await user.click(
      within(llmGroup).getByRole("button", {
        name: /Reset LLM to defaults|恢复 LLM 默认配置/i,
      }),
    );

    await waitForAutoSave();
    expect(patchSettings).toHaveBeenCalledWith({ llm_api_key: null });
  });

  it("auto-saves bool and numeric field types", async () => {
    const ingestPayload = {
      groups: [
        {
          id: "ingest_caption",
          fields: [
            {
              key: "ingest_caption_enabled",
              type: "bool" as const,
              secret: false,
              default: false,
              overridden: false,
              value: false,
            },
            {
              key: "ingest_caption_max_per_page",
              type: "int" as const,
              secret: false,
              default: 2,
              overridden: false,
              value: 2,
            },
          ],
        },
      ],
    };
    fetchSettings.mockResolvedValue(ingestPayload);
    patchSettings.mockResolvedValue(ingestPayload);

    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    await user.click(screen.getByRole("checkbox"));
    const maxInput = screen.getByLabelText(/Max VLM analyses per page|每页最多/i);
    fireEvent.change(maxInput, { target: { value: "4" } });

    await waitForAutoSave();
    expect(patchSettings).toHaveBeenLastCalledWith({
      ingest_caption_enabled: true,
      ingest_caption_max_per_page: 4,
    });
  });

  it("collapses and expands setting groups", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const toggle = screen.getByRole("button", { name: /^LLM$/i });
    expect(screen.getByLabelText(/模型|Model/i)).toBeInTheDocument();

    await user.click(toggle);
    expect(screen.queryByLabelText(/模型|Model/i)).not.toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByLabelText(/模型|Model/i)).toBeInTheDocument();
  });

  it("shows an empty state when search matches nothing", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    await user.type(screen.getByRole("searchbox"), "does-not-exist");

    expect(await screen.findByText(/No matching settings|没有匹配的设置/i)).toBeInTheDocument();
  });

  it("expands collapsed groups while searching", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const toggle = screen.getByRole("button", { name: /^LLM$/i });
    await user.click(toggle);
    expect(screen.queryByLabelText(/模型|Model/i)).not.toBeInTheDocument();

    await user.type(screen.getByRole("searchbox"), "llm_model");
    expect(screen.getByLabelText(/模型|Model/i)).toBeInTheDocument();
  });

  it("links back to the main app from the top bar", async () => {
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    expect(screen.getByRole("link", { name: /Back|返回/i })).toHaveAttribute("href", "/");
  });

  it("auto-saves a new secret field value", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const apiKeyInput = screen.getByLabelText(/API Key/i);
    await user.type(apiKeyInput, "sk-new-secret");

    await waitForAutoSave();
    expect(patchSettings).toHaveBeenCalledWith({ llm_api_key: "sk-new-secret" });
  });

  it("auto-saves float fields", async () => {
    const floatPayload = {
      groups: [
        {
          id: "rag",
          fields: [
            {
              key: "rag_step_align_min_score",
              type: "float" as const,
              secret: false,
              default: 0.5,
              overridden: false,
              value: 0.5,
            },
          ],
        },
      ],
    };
    fetchSettings.mockResolvedValue(floatPayload);
    patchSettings.mockResolvedValue(floatPayload);

    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const scoreInput = screen.getByLabelText(/Step align min score|步骤对齐最低分/i);
    fireEvent.change(scoreInput, { target: { value: "0.75" } });

    await waitForAutoSave();
    expect(patchSettings).toHaveBeenCalledWith({ rag_step_align_min_score: 0.75 });
  });

  it("does not auto-save when a numeric input is cleared back to default", async () => {
    const ingestPayload = {
      groups: [
        {
          id: "ingest_caption",
          fields: [
            {
              key: "ingest_caption_max_per_page",
              type: "int" as const,
              secret: false,
              default: 2,
              overridden: false,
              value: 2,
            },
          ],
        },
      ],
    };
    fetchSettings.mockResolvedValue(ingestPayload);
    patchSettings.mockResolvedValue(ingestPayload);

    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    const maxInput = screen.getByLabelText(/Max VLM analyses per page|每页最多/i);
    fireEvent.change(maxInput, { target: { value: "4" } });
    await waitForAutoSave();
    patchSettings.mockClear();

    fireEvent.change(maxInput, { target: { value: "" } });
    expect(maxInput).toHaveValue(2);

    await new Promise((resolve) => window.setTimeout(resolve, 600));
    expect(patchSettings).not.toHaveBeenCalled();
  });

  it("shows the masked secret hint when the field is set", async () => {
    const secretPayload = {
      groups: [
        {
          id: "llm",
          fields: [
            {
              key: "llm_api_key",
              type: "secret" as const,
              secret: true,
              default: "",
              overridden: true,
              value: null,
              set: true,
              masked: "sk-test****",
            },
          ],
        },
      ],
    };
    fetchSettings.mockResolvedValue(secretPayload);

    renderPage();

    await screen.findByRole("heading", { name: /Management|管理/i });
    expect(screen.getByText(/Currently set: sk-test\*\*\*\*|当前已设置：sk-test\*\*\*\*/i)).toBeInTheDocument();
  });
});
