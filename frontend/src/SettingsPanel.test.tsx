/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
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
});
