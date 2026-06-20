/** @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPanel from "./SettingsPanel";
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

function renderPanel(open = true, onClose = vi.fn()) {
  return render(
    <I18nProvider>
      <SettingsPanel open={open} onClose={onClose} />
    </I18nProvider>,
  );
}

describe("SettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchSettings.mockResolvedValue(samplePayload);
    patchSettings.mockResolvedValue(samplePayload);
  });

  it("does not render when closed", () => {
    renderPanel(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("loads settings and renders fields when opened", async () => {
    renderPanel();

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(/模型|Model/i)).toBeInTheDocument();
  });

  it("filters fields by search query", async () => {
    const user = userEvent.setup();
    renderPanel();

    await screen.findByRole("dialog");
    await user.type(screen.getByRole("searchbox"), "llm_api_key");

    expect(screen.getByLabelText(/API Key/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^模型$|^Model$/i)).not.toBeInTheDocument();
  });

  it("saves dirty field changes", async () => {
    const user = userEvent.setup();
    renderPanel();

    await screen.findByRole("dialog");
    const modelInput = screen.getByLabelText(/模型|Model/i);
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4.1");

    const saveButton = screen.getByRole("button", { name: /保存|Save/i });
    expect(saveButton).toBeEnabled();

    await user.click(saveButton);

    await waitFor(() => {
      expect(patchSettings).toHaveBeenCalledWith({ llm_model: "gpt-4.1" });
    });
    expect(await screen.findByText(/已保存|Settings saved/i)).toBeInTheDocument();
  });

  it("shows a load error when settings cannot be fetched", async () => {
    fetchSettings.mockRejectedValue(new Error("Settings unavailable"));
    renderPanel();

    expect(await screen.findByText(/Settings unavailable/)).toBeInTheDocument();
  });

  it("shows a save error when patch settings fails", async () => {
    patchSettings.mockRejectedValue(new Error("Save rejected"));
    const user = userEvent.setup();
    renderPanel();

    await screen.findByRole("dialog");
    const modelInput = screen.getByLabelText(/模型|Model/i);
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4.1");
    await user.click(screen.getByRole("button", { name: /保存|Save/i }));

    expect(await screen.findByText(/Save rejected/)).toBeInTheDocument();
  });

  it("closes on Escape key", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderPanel(true, onClose);

    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when clicking the backdrop", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderPanel(true, onClose);

    await screen.findByRole("dialog");
    await user.click(document.querySelector(".settings-panel-backdrop") as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("resets an overridden field back to the default", async () => {
    const user = userEvent.setup();
    renderPanel();

    await screen.findByRole("dialog");
    const apiKeyField = screen.getByLabelText(/API Key/i).closest(".settings-field") as HTMLElement;
    await user.click(within(apiKeyField).getByRole("button", { name: /Reset|重置/i }));

    const saveButton = screen.getByRole("button", { name: /保存|Save/i });
    expect(saveButton).toBeEnabled();
    await user.click(saveButton);

    await waitFor(() => {
      expect(patchSettings).toHaveBeenCalledWith({ llm_api_key: null });
    });
  });

  it("renders bool and numeric field types", async () => {
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
    renderPanel();

    await screen.findByRole("dialog");
    await user.click(screen.getByRole("checkbox"));
    const maxInput = screen.getByLabelText(/Max VLM analyses per page|每页最多/i);
    fireEvent.change(maxInput, { target: { value: "4" } });

    await user.click(screen.getByRole("button", { name: /保存|Save/i }));

    await waitFor(() => {
      expect(patchSettings).toHaveBeenLastCalledWith({
        ingest_caption_enabled: true,
        ingest_caption_max_per_page: 4,
      });
    });
  });

  it("collapses and expands setting groups", async () => {
    const user = userEvent.setup();
    renderPanel();

    await screen.findByRole("dialog");
    const toggle = screen.getByRole("button", { name: /LLM|大模型/i });
    expect(screen.getByLabelText(/模型|Model/i)).toBeInTheDocument();

    await user.click(toggle);
    expect(screen.queryByLabelText(/模型|Model/i)).not.toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByLabelText(/模型|Model/i)).toBeInTheDocument();
  });

  it("shows an empty state when search matches nothing", async () => {
    const user = userEvent.setup();
    renderPanel();

    await screen.findByRole("dialog");
    await user.type(screen.getByRole("searchbox"), "does-not-exist");

    expect(await screen.findByText(/No matching settings|没有匹配的设置/i)).toBeInTheDocument();
  });
});
