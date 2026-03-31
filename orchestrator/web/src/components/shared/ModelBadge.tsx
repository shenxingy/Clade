import { cn } from '../../lib/utils';

const colors: Record<string, string> = {
  haiku:  'text-blue-300  bg-blue-300/10',
  sonnet: 'text-purple-300 bg-purple-300/10',
  opus:   'text-orange-300 bg-orange-300/10',
};

export function ModelBadge({ model }: { model: string }) {
  const key = model.toLowerCase().includes('haiku') ? 'haiku'
            : model.toLowerCase().includes('opus') ? 'opus'
            : 'sonnet';
  return (
    <span className={cn('px-1.5 py-0.5 rounded text-xs font-mono', colors[key])}>
      {key}
    </span>
  );
}
