/** @vitest-environment jsdom */
import { createRef, type ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Composer from "./Composer";
import { I18nProvider } from "./i18n";

function renderComposer(overrides: Partial<ComponentProps<typeof Composer>> = {}) {
  const onSend = vi.fn();
  const onInputChange = vi.fn();
  const onStartRecording = vi.fn();
  const onStopRecording = vi.fn();

  const view = render(
    <I18nProvider>
      <Composer
        input=""
        loading={false}
        recording={false}
        textareaRef={createRef()}
        onInputChange={onInputChange}
        onSend={onSend}
        onStartRecording={onStartRecording}
        onStopRecording={onStopRecording}
        {...overrides}
      />
    </I18nProvider>,
  );

  return { ...view, onSend, onInputChange, onStartRecording, onStopRecording };
}

describe("Composer", () => {
  it("disables send when input is empty", () => {
    renderComposer();

    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: /发送|Send/i })).toBeDisabled();
  });

  it("sends on Enter without Shift", async () => {
    const user = userEvent.setup();
    const { onSend } = renderComposer({ input: "question" });

    await user.click(screen.getByRole("textbox"));
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("toggles recording via the mic button", async () => {
    const user = userEvent.setup();
    const { onStartRecording, onStopRecording, rerender } = renderComposer({ recording: false });

    await user.click(screen.getByRole("button", { name: /语音|Voice/i }));
    expect(onStartRecording).toHaveBeenCalledTimes(1);

    rerender(
      <I18nProvider>
        <Composer
          input=""
          loading={false}
          recording
          textareaRef={createRef()}
          onInputChange={vi.fn()}
          onSend={vi.fn()}
          onStartRecording={onStartRecording}
          onStopRecording={onStopRecording}
        />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: /停止|Stop/i }));
    expect(onStopRecording).toHaveBeenCalledTimes(1);
  });
});
