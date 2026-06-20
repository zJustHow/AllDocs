import { describe, expect, it } from "vitest";
import type { Root } from "mdast";
import { citationPlaceholder } from "./citationPlaceholders";
import { remarkCitationPlaceholders } from "./remarkCitationPlaceholders";

function transformTree(tree: Root): Root {
  const plugin = remarkCitationPlaceholders();
  plugin(tree);
  return tree;
}

describe("remarkCitationPlaceholders", () => {
  it("splits text nodes into citationRef elements", () => {
    const tree: Root = {
      type: "root",
      children: [
        {
          type: "paragraph",
          children: [
            {
              type: "text",
              value: `See ${citationPlaceholder(0)} and ${citationPlaceholder(2)}.`,
            },
          ],
        },
      ],
    };

    transformTree(tree);
    const paragraph = tree.children[0];
    expect(paragraph?.type).toBe("paragraph");
    if (paragraph?.type !== "paragraph") return;

    expect(paragraph.children).toHaveLength(5);
    expect(paragraph.children[0]).toMatchObject({ type: "text", value: "See " });
    expect(paragraph.children[1]).toMatchObject({
      type: "citationRef",
      data: { hProperties: { dataIndex: 0 } },
    });
    expect(paragraph.children[3]).toMatchObject({
      type: "citationRef",
      data: { hProperties: { dataIndex: 2 } },
    });
  });

  it("leaves plain text nodes unchanged", () => {
    const tree: Root = {
      type: "root",
      children: [
        {
          type: "paragraph",
          children: [{ type: "text", value: "No citations here." }],
        },
      ],
    };

    transformTree(tree);
    const paragraph = tree.children[0];
    if (paragraph?.type !== "paragraph") return;

    expect(paragraph.children).toEqual([{ type: "text", value: "No citations here." }]);
  });
});
