import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownTextProps {
  content: string;
  /** Use span instead of p for paragraph nodes so text can flow inline with citation badges. */
  inline?: boolean;
}

const inlineComponents: Components = {
  p: ({ children }) => <span className="md-inline">{children}</span>,
};

export default function MarkdownText({ content, inline = false }: MarkdownTextProps) {
  if (!content.trim()) {
    return null;
  }

  return (
    <div className="markdown-preview">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={inline ? inlineComponents : undefined}
        urlTransform={(url) => url}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
