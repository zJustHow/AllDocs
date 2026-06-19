import type { Parent, PhrasingContent, Root, Text } from "mdast";
import type { Plugin } from "unified";
import { visit } from "unist-util-visit";
import { CITATION_PLACEHOLDER_RE } from "./citationPlaceholders";

function splitTextOnPlaceholders(value: string): PhrasingContent[] {
  const parts: PhrasingContent[] = [];
  let last = 0;
  const pattern = new RegExp(CITATION_PLACEHOLDER_RE.source, "g");
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(value)) !== null) {
    if (match.index > last) {
      parts.push({ type: "text", value: value.slice(last, match.index) });
    }
    const index = Number(match[1]);
    parts.push({
      type: "citationRef",
      data: {
        hName: "cite",
        hProperties: { dataIndex: index },
      },
    } as PhrasingContent);
    last = match.index + match[0].length;
  }

  if (last < value.length) {
    parts.push({ type: "text", value: value.slice(last) });
  }

  return parts.length ? parts : [{ type: "text", value }];
}

export const remarkCitationPlaceholders: Plugin<[], Root> = () => (tree) => {
  visit(tree, "text", (node: Text, index, parent: Parent | undefined) => {
    if (!parent || index === null || typeof index !== "number") return;

    CITATION_PLACEHOLDER_RE.lastIndex = 0;
    if (!CITATION_PLACEHOLDER_RE.test(node.value)) return;

    const replacement = splitTextOnPlaceholders(node.value);
    if (replacement.length === 1 && replacement[0].type === "text") return;

    parent.children.splice(index, 1, ...replacement);
  });
};
