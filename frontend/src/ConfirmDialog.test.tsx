/** @vitest-environment jsdom */
import { type ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ConfirmDialog from "./ConfirmDialog";
import { I18nProvider } from "./i18n";

function renderDialog(overrides: Partial<ComponentProps<typeof ConfirmDialog>> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();

  render(
    <I18nProvider>
      <ConfirmDialog
        open
        message="Delete this document?"
        title="Confirm delete"
        variant="danger"
        onConfirm={onConfirm}
        onCancel={onCancel}
        {...overrides}
      />
    </I18nProvider>,
  );

  return { onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  it("does not render when closed", () => {
    render(
      <I18nProvider>
        <ConfirmDialog
          open={false}
          message="Hidden"
          onConfirm={vi.fn()}
          onCancel={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("calls confirm and cancel handlers from action buttons", async () => {
    const user = userEvent.setup();
    const { onConfirm, onCancel } = renderDialog();

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("Delete this document?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /确认|Confirm/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /取消|Cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderDialog();

    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
