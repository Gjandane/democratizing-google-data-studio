import { Circle, CircleCheck, CircleMinus, CircleX, RotateCw, WandSparkles } from 'lucide-react';
import type { Recipe } from '../../../api/types';
import { Button } from '../../../components/Button';
import { Panel } from '../../../components/Panel';
import { Spinner } from '../../../components/Spinner';
import { runningOpId, type BuildRun } from './buildRun';

type OpState = 'pending' | 'running' | 'ok' | 'failed' | 'skipped';

const WORDS: Record<OpState, string> = { pending: 'Pending', running: 'Running', ok: 'Done', failed: 'Failed', skipped: 'Skipped' };

function StatusIcon({ state }: { state: OpState }) {
  switch (state) {
    case 'running':
      return <Spinner size="sm" className="text-primary" />;
    case 'ok':
      return <CircleCheck aria-hidden="true" className="size-4 shrink-0 text-success" />;
    case 'failed':
      return <CircleX aria-hidden="true" className="size-4 shrink-0 text-danger" />;
    case 'skipped':
      return <CircleMinus aria-hidden="true" className="size-4 shrink-0 text-text-muted" />;
    default:
      return <Circle aria-hidden="true" className="size-4 shrink-0 text-text-muted" />;
  }
}

interface RecipePanelProps {
  recipe: Recipe | null;
  run: BuildRun;
  generating: boolean;
  error: string | null;
  onGenerate: () => void;
}

/** The recipe: the engine's CLI lines, ticked off as `build.op` events arrive. */
export function RecipePanel({ recipe, run, generating, error, onGenerate }: RecipePanelProps) {
  const current = recipe ? runningOpId(run, recipe.ops) : null;
  const done = recipe ? recipe.ops.filter((op) => run.ops[op.op_id]).length : 0;
  const showProgress = recipe && (run.running || run.finished);
  const count = recipe ? `${recipe.ops.length} ${recipe.ops.length === 1 ? 'op' : 'ops'}` : '';
  return (
    <Panel
      title={
        <span>
          Recipe
          {recipe && (
            <span className="font-normal text-text-muted">
              {' '}
              · {count}
              {showProgress ? `, ${done} of ${recipe.ops.length} done` : ''}
            </span>
          )}
        </span>
      }
      actions={
        recipe && !run.running ? (
          <Button variant="ghost" size="sm" icon={<RotateCw aria-hidden="true" />} loading={generating} onClick={onGenerate}>
            Regenerate
          </Button>
        ) : undefined
      }
    >
      {recipe ? (
        <ol aria-label="Recipe" className="divide-y divide-border">
          {recipe.ops.map((op) => {
            const result = run.ops[op.op_id];
            const state: OpState = result ? result.status : current === op.op_id ? 'running' : 'pending';
            return (
              <li key={op.op_id} data-op-id={op.op_id} data-status={state} className="flex items-start gap-3 px-4 py-2">
                <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center">
                  <StatusIcon state={state} />
                  <span className="sr-only">{WORDS[state]}</span>
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-caption text-text-muted">{op.op_id}</p>
                  <p className="font-mono text-label break-all text-text">{op.line}</p>
                  {state === 'failed' && result?.message && <p className="mt-0.5 text-caption text-danger">{result.message}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="flex flex-col items-start gap-3 px-4 py-4">
          <p className="text-body text-text-muted">The recipe lists the steps the engine takes in Data Studio. Generate it from the prototype.</p>
          <Button variant="primary" icon={<WandSparkles aria-hidden="true" />} loading={generating} onClick={onGenerate}>
            Generate recipe
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="border-t border-border px-4 py-2 text-label text-danger">
          {error}
        </p>
      )}
    </Panel>
  );
}
