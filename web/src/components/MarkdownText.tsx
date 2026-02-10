"use client";

import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";

interface MarkdownTextProps {
  children: string;
  className?: string;
}

// Custom components for markdown rendering
const components: Components = {
  // Links open in new tab
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-[var(--primary)] hover:text-[var(--primary-hover)] underline"
    >
      {children}
    </a>
  ),
  // Code blocks
  code: ({ children, className }) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code className="rounded bg-[var(--surface)] px-1 py-0.5 font-mono text-sm text-[var(--foreground)]">
          {children}
        </code>
      );
    }
    return (
      <code className="block overflow-x-auto rounded bg-[var(--surface)] p-2 font-mono text-sm text-[var(--foreground)]">
        {children}
      </code>
    );
  },
  // Pre blocks (code blocks wrapper)
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded bg-[var(--surface)] p-2">
      {children}
    </pre>
  ),
  // Strong/bold
  strong: ({ children }) => (
    <strong className="font-semibold text-[var(--foreground)]">{children}</strong>
  ),
  // Emphasis/italic
  em: ({ children }) => (
    <em className="italic">{children}</em>
  ),
  // Paragraphs
  p: ({ children }) => (
    <span>{children}</span>
  ),
  // Strikethrough
  del: ({ children }) => (
    <del className="text-[var(--muted)] line-through">{children}</del>
  ),
};

/**
 * Process Telegram-style formatting that markdown doesn't handle:
 * - Convert URLs to markdown links
 * - Convert hashtags to styled spans
 */
function preprocessText(text: string): string {
  // Convert plain URLs to markdown links (if not already in markdown format)
  // Match URLs not already in [text](url) format
  const urlRegex = /(?<!\]\()https?:\/\/[^\s<>\[\]]+/g;
  const processed = text.replace(urlRegex, (url) => `[${url}](${url})`);

  return processed;
}

export function MarkdownText({ children, className = "" }: MarkdownTextProps) {
  const processedText = preprocessText(children);

  return (
    <div className={`markdown-text ${className}`}>
      <ReactMarkdown components={components}>
        {processedText}
      </ReactMarkdown>
    </div>
  );
}
