import { useEffect, useState, useRef } from 'react';
import { X } from 'lucide-react';
import { useSessionStore } from '../../stores/sessionStore';
import { settings as settingsApi } from '../../lib/api';
import type { GlobalSettings } from '../../lib/types';

interface Props {
  open: boolean;
  onClose: () => void;
}

const MODEL_OPTIONS = ['sonnet', 'opus', 'haiku'];

export function SettingsPanel({ open, onClose }: Props) {
  const { settings, setSettings } = useSessionStore();
  const [form, setForm] = useState<GlobalSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Load settings when panel opens
  useEffect(() => {
    if (open && !form) {
      settingsApi.get().then(data => {
        const s = data as GlobalSettings;
        setSettings(s);
        setForm(s);
      }).catch(console.error);
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync form when store settings change externally
  useEffect(() => {
    if (settings && !form) setForm(settings);
  }, [settings]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const patch = (key: keyof GlobalSettings, value: unknown) => {
    setForm(f => f ? { ...f, [key]: value } : f);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      if (!form) return;
      setSaving(true);
      try {
        const updated = await settingsApi.update({ [key]: value }) as GlobalSettings;
        setSettings(updated);
        setForm(updated);
      } catch (e) {
        console.error(e);
      } finally {
        setSaving(false);
      }
    }, 400);
  };

  const f = form;

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />

      {/* Panel */}
      <aside className="w-80 bg-background border-l border-border flex flex-col overflow-hidden">
        <header className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <span className="font-semibold text-sm">Settings</span>
          <div className="flex items-center gap-2">
            {saving && <span className="text-xs text-muted-foreground">saving…</span>}
            <button onClick={onClose} className="p-1 rounded hover:bg-secondary text-muted-foreground">
              <X size={14} />
            </button>
          </div>
        </header>

        {!f ? (
          <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground">Loading…</div>
        ) : (
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">
            {/* Workers */}
            <section>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Workers</p>
              <Row label="Max workers">
                <input type="number" min={0} value={f.max_workers}
                  onChange={e => patch('max_workers', parseInt(e.target.value) || 0)}
                  className="input-sm w-20" />
              </Row>
              <Row label="Min workers">
                <input type="number" min={1} value={f.min_workers ?? 1}
                  onChange={e => patch('min_workers', parseInt(e.target.value) || 1)}
                  className="input-sm w-20" />
              </Row>
              <Row label="Default model">
                <select value={f.default_model} onChange={e => patch('default_model', e.target.value)}
                  className="input-sm">
                  {MODEL_OPTIONS.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </Row>
              <Row label="Stuck timeout (min)">
                <input type="number" min={1} value={f.stuck_timeout_minutes ?? 15}
                  onChange={e => patch('stuck_timeout_minutes', parseInt(e.target.value) || 15)}
                  className="input-sm w-20" />
              </Row>
            </section>

            {/* Automation */}
            <section>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Automation</p>
              <Toggle label="Auto-start tasks" value={f.auto_start} onChange={v => patch('auto_start', v)} />
              <Toggle label="Auto-push commits" value={f.auto_push} onChange={v => patch('auto_push', v)} />
              <Toggle label="Auto-merge PRs" value={f.auto_merge} onChange={v => patch('auto_merge', v)} />
              <Toggle label="Auto-review workers" value={f.auto_review} onChange={v => patch('auto_review', v)} />
              <Toggle label="Auto-oracle eval" value={f.auto_oracle} onChange={v => patch('auto_oracle', v)} />
              <Toggle label="Auto-scale workers" value={f.auto_scale} onChange={v => patch('auto_scale', v)} />
              <Toggle label="Model routing" value={f.auto_model_routing} onChange={v => patch('auto_model_routing', v)} />
            </section>

            {/* Budget */}
            <section>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Budget</p>
              <Row label="Cost budget ($)">
                <input type="number" min={0} step={0.5} value={f.cost_budget ?? 0}
                  onChange={e => patch('cost_budget', parseFloat(e.target.value) || 0)}
                  className="input-sm w-24" />
              </Row>
            </section>

            {/* GitHub */}
            <section>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">GitHub</p>
              <Toggle label="Issues sync" value={f.github_issues_sync} onChange={v => patch('github_issues_sync', v)} />
              <Row label="Issues label">
                <input type="text" value={f.github_issues_label ?? ''}
                  onChange={e => patch('github_issues_label', e.target.value)}
                  className="input-sm w-32" />
              </Row>
            </section>

            {/* Notifications */}
            <section>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Notifications</p>
              <Row label="Webhook URL">
                <input type="text" value={f.notification_webhook ?? ''}
                  placeholder="https://…"
                  onChange={e => patch('notification_webhook', e.target.value)}
                  className="input-sm w-48" />
              </Row>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-foreground">{label}</span>
      {children}
    </div>
  );
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-foreground">{label}</span>
      <button
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${value ? 'bg-primary' : 'bg-secondary border border-border'}`}
      >
        <span className={`inline-block h-3 w-3 rounded-full bg-white shadow transition-transform ${value ? 'translate-x-3.5' : 'translate-x-0.5'}`} />
      </button>
    </div>
  );
}
