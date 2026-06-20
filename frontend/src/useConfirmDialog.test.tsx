/** @vitest-environment jsdom */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { useConfirmDialog } from "./useConfirmDialog";
import { I18nProvider } from "./i18n";

function ConfirmHarness() {
  const { confirm, dialog } = useConfirmDialog();

  return (
    <>
      <button
        type="button"
        onClick={() => {
          void confirm("Delete this item?").then((accepted) => {
            document.body.dataset.confirmResult = accepted ? "yes" : "no";
          });
        }}
      >
        Ask
      </button>
      {dialog}
    </>
  );
}

describe("useConfirmDialog", () => {
  it("resolves true when confirmed and false when cancelled", async () => {
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <ConfirmHarness />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /确认|Confirm/i }));
    expect(document.body.dataset.confirmResult).toBe("yes");

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Ask" }));
    });
    await user.click(screen.getByRole("button", { name: /取消|Cancel/i }));
    expect(document.body.dataset.confirmResult).toBe("no");
  });
});
