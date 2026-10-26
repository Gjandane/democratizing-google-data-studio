import { Fragment, type ReactNode } from 'react';

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Numbers align right with tabular figures. */
  align?: 'left' | 'right';
  /** Ids, column names and recipe lines use the mono face. */
  mono?: boolean;
  className?: string;
}

interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Names the table for screen readers; shown only if `showCaption`. */
  caption: string;
  showCaption?: boolean;
  /** Footer cells (totals) by column id. */
  footer?: Partial<Record<string, ReactNode>>;
  /** A full-width row under a row (an expanded detail), or null for none. */
  rowDetail?: (row: T) => ReactNode;
  className?: string;
}

/** Footer cells (totals, their label) keep the body font even in a mono column. */
const cellClass = <T,>(column: Column<T>, mono = column.mono) =>
  `px-3 ${column.align === 'right' ? 'text-right tabular-nums' : 'text-left'} ${mono ? 'font-mono' : ''} ${column.className ?? ''}`;

/** A dense data table. */
export function Table<T>({ columns, rows, rowKey, caption, showCaption = false, footer, rowDetail, className = '' }: TableProps<T>) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full border-collapse text-label text-text">
        <caption className={showCaption ? 'pb-2 text-left text-body font-semibold' : 'sr-only'}>{caption}</caption>
        <thead>
          <tr className="border-b border-border bg-surface-muted">
            {columns.map((column) => (
              <th key={column.id} scope="col" className={`h-8 font-medium text-text-muted ${cellClass(column)}`}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const detail = rowDetail?.(row) ?? null;
            return (
              <Fragment key={rowKey(row)}>
                <tr className="border-b border-border last:border-b-0">
                  {columns.map((column) => (
                    <td key={column.id} className={`h-9 py-1.5 ${cellClass(column)}`}>
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
                {detail !== null && (
                  <tr className="border-b border-border bg-surface-muted last:border-b-0">
                    <td colSpan={columns.length} className="px-3 py-3">
                      {detail}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
        {footer && (
          <tfoot>
            <tr className="border-t border-border-strong bg-surface-muted font-medium">
              {columns.map((column) => (
                <td key={column.id} className={`h-9 ${cellClass(column, false)}`}>
                  {footer[column.id]}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
