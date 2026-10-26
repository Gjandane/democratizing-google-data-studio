import ReactMarkdown, { type Components } from 'react-markdown';

const components: Components = {
  h1: ({ node: _node, ...props }) => <h3 className="text-title font-semibold text-text [&:not(:first-child)]:mt-4" {...props} />,
  h2: ({ node: _node, ...props }) => <h4 className="mt-4 text-body font-semibold text-text [overflow-wrap:anywhere]" {...props} />,
  h3: ({ node: _node, ...props }) => <h5 className="mt-3 text-body font-semibold text-text" {...props} />,
  h4: ({ node: _node, ...props }) => <h6 className="mt-3 text-label font-semibold text-text" {...props} />,
  h5: ({ node: _node, ...props }) => <h6 className="mt-3 text-label font-semibold text-text" {...props} />,
  h6: ({ node: _node, ...props }) => <h6 className="mt-3 text-label font-semibold text-text" {...props} />,
  p: ({ node: _node, ...props }) => <p className="mt-1.5" {...props} />,
  ul: ({ node: _node, ...props }) => <ul className="mt-1.5 list-disc pl-5" {...props} />,
  ol: ({ node: _node, ...props }) => <ol className="mt-1.5 list-decimal pl-5" {...props} />,
  li: ({ node: _node, ...props }) => <li className="[&:not(:first-child)]:mt-1" {...props} />,
  blockquote: ({ node: _node, ...props }) => <blockquote className="mt-1.5 border-l-2 border-border-strong pl-3 text-text-muted" {...props} />,
  pre: ({ node: _node, ...props }) => (
    <pre className="mt-1.5 overflow-x-auto rounded-control bg-surface-muted p-2 text-caption [&_code]:bg-transparent [&_code]:p-0" {...props} />
  ),
  code: ({ node: _node, ...props }) => <code className="rounded-control bg-surface-muted px-1 font-mono text-caption" {...props} />,
  a: ({ node: _node, children, ...props }) => (
    <a className="text-primary underline hover:text-primary-hover" target="_blank" rel="noopener noreferrer" {...props}>
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  ),
  strong: ({ node: _node, ...props }) => <strong className="font-semibold" {...props} />,
  // Only the backend's /api is ever called: an image in a brief shows as its alt text, never loads.
  img: ({ alt }) => (alt ? <span className="text-text-muted">[{alt}]</span> : null),
  hr: () => <hr className="mt-4 border-border" />,
};

/**
 * A design brief's Markdown (api.md 3.0 `BriefRecord.markdown`). Raw HTML is dropped, never
 * rendered; headings start at h3 so the brief sits under its panel's h2.
 */
export function BriefMarkdown({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={`min-w-0 text-body text-text [overflow-wrap:anywhere] ${className}`}>
      <ReactMarkdown skipHtml components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
