/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ImageLightbox from "./ImageLightbox";
import { I18nProvider } from "./i18n";

describe("ImageLightbox", () => {
  it("does not render when closed", () => {
    render(
      <I18nProvider>
        <ImageLightbox open={false} src="/x.png" alt="Figure" onClose={vi.fn()} />
      </I18nProvider>,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders image in a portal and closes on backdrop click", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <I18nProvider>
        <ImageLightbox
          open
          src="/figure.png"
          alt="Robot diagram"
          caption="Figure 1"
          onClose={onClose}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Robot diagram" })).toHaveAttribute(
      "src",
      "/figure.png",
    );
    expect(screen.getByText("Figure 1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /关闭|Close enlarged/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <I18nProvider>
        <ImageLightbox open src="/x.png" alt="Figure" onClose={onClose} />
      </I18nProvider>,
    );

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
