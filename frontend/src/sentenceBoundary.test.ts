import { describe, expect, it } from "vitest";
import { forEachTextRunBoundary } from "./sentenceBoundary";

function collectRuns(text: string): string[] {
  const runs: string[] = [];
  forEachTextRunBoundary(
    text,
    (run) => {
      runs.push(run);
    },
    () => {},
  );
  return runs;
}

describe("forEachTextRunBoundary", () => {
  it("splits on Chinese and English sentence punctuation", () => {
    const runs = collectRuns(
      "确认精度异常表现。第一步：机器人轴零点标定. Check TCP settings: verify the tool.",
    );

    expect(runs).toEqual([
      "确认精度异常表现。",
      "第一步：机器人轴零点标定. ",
      "Check TCP settings: ",
      "verify the tool.",
    ]);
  });

  it("keeps text without a boundary as a single run", () => {
    expect(collectRuns("仅有一句话带引用")).toEqual(["仅有一句话带引用"]);
  });

  it("does not split numbered list markers", () => {
    const text =
      "1. 接通伺服电源（回放模式下）：\n" +
      "   - 按下示教器上的【伺服准备】键 [1]。\n" +
      "2. 启动执行：\n" +
      "   - 按下【启动】键 [3]。";

    const runs = collectRuns(text);

    expect(runs).toHaveLength(2);
    expect(runs[0]).toMatch(/^1\. 接通伺服电源/);
    expect(runs[1]).toContain("2. 启动执行");
  });

  it("includes trailing spaces in the run after a boundary", () => {
    const runs = collectRuns("第一句。  第二句！");

    expect(runs).toEqual(["第一句。  ", "第二句！"]);
  });
});
