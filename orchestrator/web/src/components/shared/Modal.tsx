import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useRef, type ReactNode } from 'react';

export function Modal({ title, children, onClose }: {
  title: string; children: ReactNode; onClose: () => void;
}) {
  const opener = useRef(document.activeElement as HTMLElement | null);
  return (
    <Dialog.Root open onOpenChange={open => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className="modal-content" aria-describedby={undefined}
          onOpenAutoFocus={event => {
            const input = document.querySelector<HTMLElement>('[role="dialog"] input, [role="dialog"] textarea');
            if (input) { event.preventDefault(); input.focus(); }
          }}
          onCloseAutoFocus={event => { event.preventDefault(); opener.current?.focus(); }}>
          <div className="modal-heading">
            <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
            <Dialog.Close className="ui-button ui-icon" aria-label="Close dialog"><X size={18} /></Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
