import ReactMarkdown, { type Components } from 'react-markdown';

const components: Components = {
  p: ({ node: _node, ...props }) => <p className="[&:not(:first-child)]:mt-2" {...props} />,
  ul: ({ node: _node, ...props }) => <ul className="list-disc pl-5 [&:not(:first-child)]:mt-2" {...props} />,
  ol: ({ node: _node, ...props }) => <ol className="list-decimal pl-5 [&:not(:first-child)]:mt-2" {...props} />,
  li: ({ node: _node, ...props }) => <li className="[&:not(:first-child)]:mt-1" {...props} />,
  pre: ({ node: _node, ...props }) => (
    <pre className="overflow-x-auto rounded-control bg-surface p-2 text-caption [&:not(:first-child)]:mt-2 [&_code]:bg-transparent [&_code]:p-0" {...props} />
  ),
  code: ({ node: _node, ...props }) => <code className="rounded-control bg-surface px-1 font-mono text-caption" {...props} />,
  a: ({ node: _node, children, ...props }) => (
    <a className="text-primary underline hover:text-primary-hover" target="_blank" rel="noopener noreferrer" {...props}>
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  ),
  strong: ({ node: _node, ...props }) => <strong className="font-semibold" {...props} />,
};

/** Markdown for chat bubbles and question text: tight spacing, wraps long words. */
export function Markdown({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={`min-w-0 [overflow-wrap:anywhere] ${className}`}>
      <ReactMarkdown components={components}>{children}</ReactMarkdown>
    </div>
  );
}
