/** @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppLink } from "./AppLink";
import { navigate, useAppPath } from "./routing";

function PathProbe() {
  const path = useAppPath();
  return <span data-testid="path">{path}</span>;
}

describe("routing", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("updates path via client navigation", async () => {
    render(<PathProbe />);
    expect(screen.getByTestId("path")).toHaveTextContent("/");

    navigate("/profile");
    await waitFor(() => {
      expect(screen.getByTestId("path")).toHaveTextContent("/profile");
    });

    navigate("/");
    await waitFor(() => {
      expect(screen.getByTestId("path")).toHaveTextContent("/");
    });
  });

  it("AppLink prevents full reload for same-origin paths", () => {
    const pushState = vi.spyOn(window.history, "pushState");

    render(
      <AppLink href="/settings" aria-label="Settings">
        Settings
      </AppLink>,
    );

    fireEvent.click(screen.getByRole("link", { name: "Settings" }));

    expect(pushState).toHaveBeenCalledWith(null, "", "/settings");
  });
});
