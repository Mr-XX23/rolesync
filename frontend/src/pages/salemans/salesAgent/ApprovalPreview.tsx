import React from 'react';
import { AlertTriangle, Undo2 } from 'lucide-react';
import { previewKind } from './approvalKinds';
import type { ApprovalCardModel } from './chatState';

type Preview = Record<string, unknown>;

const text = (value: unknown): string => (value === null || value === undefined ? '' : String(value));
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

export const PreviewRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex gap-3">
    <span className="w-20 shrink-0 text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground pt-0.5">
      {label}
    </span>
    <span className="text-foreground break-words min-w-0">{value}</span>
  </div>
);

const TextBlock: React.FC<{ value: string }> = ({ value }) => (
  <div className="mt-2 rounded-xl border border-border/60 bg-background/60 px-4 py-3 text-sm text-foreground whitespace-pre-wrap max-h-72 overflow-y-auto leading-relaxed">
    {value}
  </div>
);

const DataTable: React.FC<{ columns: string[]; rows: React.ReactNode[][]; numeric?: number[] }> = ({ columns, rows, numeric = [] }) => (
  <div className="mt-2 overflow-x-auto rounded-xl border border-border/60">
    <table className="w-full text-xs">
      <thead className="bg-muted/40">
        <tr>
          {columns.map((column, index) => (
            <th
              key={`${column}-${index}`}
              className={`px-3 py-2 font-mono font-bold uppercase tracking-wider text-[10px] text-muted-foreground ${numeric.includes(index) ? 'text-right' : 'text-left'}`}
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr key={rowIndex} className="border-t border-border/50">
            {row.map((cell, index) => (
              <td key={index} className={`px-3 py-2 text-foreground align-top ${numeric.includes(index) ? 'text-right tabular-nums' : ''}`}>
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const Warning: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-200">
    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
    <div className="min-w-0">{children}</div>
  </div>
);

/** "2026-09-15T15:00" → "Tue, 15 Sep 2026 15:00" without shifting it to the viewer's zone. */
function wallClock(value: unknown): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text(value));
  if (!match) return text(value);
  const [, year, month, day, hour, minute] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  const label = date.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  return `${label} ${hour}:${minute}`;
}

const money = (currency: unknown, amount: unknown): string => `${text(currency)} ${text(amount)}`.trim();

// --------------------------------------------------------------------------- per kind

const EmailPreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="To" value={list(preview.to).map(text).join(', ')} />
    {list(preview.cc).length > 0 && <PreviewRow label="Cc" value={list(preview.cc).map(text).join(', ')} />}
    {list(preview.bcc).length > 0 && <PreviewRow label="Bcc" value={list(preview.bcc).map(text).join(', ')} />}
    <PreviewRow label="Subject" value={text(preview.subject)} />
    <TextBlock value={text(preview.body)} />
  </div>
);

const CalendarPreview: React.FC<{ preview: Preview }> = ({ preview }) => {
  const end = text(preview.end).slice(0, 10) === text(preview.start).slice(0, 10) ? text(preview.end).slice(11, 16) : wallClock(preview.end);
  const attendees = list(preview.attendees).map(text);
  return (
    <div className="space-y-2 text-sm">
      <PreviewRow label="Event" value={<span className="font-semibold">{text(preview.title)}</span>} />
      <PreviewRow label="When" value={`${wallClock(preview.start)} – ${end} (${text(preview.time_zone)})`} />
      <PreviewRow label="Guests" value={attendees.length ? attendees.join(', ') : 'Only you'} />
      {text(preview.location) && <PreviewRow label="Where" value={text(preview.location)} />}
      <PreviewRow label="Video" value={preview.video_link ? 'Google Meet link added' : 'No video link'} />
      {attendees.length > 0 && (
        <PreviewRow label="Invites" value={preview.notify_attendees ? 'Emailed to guests' : 'Not emailed'} />
      )}
      {text(preview.description) && <TextBlock value={text(preview.description)} />}
    </div>
  );
};

const SlackPreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="Channel" value={`#${text(preview.channel)}`} />
    {text(preview.thread_ts) && <PreviewRow label="Thread" value="Reply in thread" />}
    <TextBlock value={text(preview.text)} />
  </div>
);

const NotionPreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="Title" value={<span className="font-semibold">{text(preview.title)}</span>} />
    <PreviewRow label="Under" value={<span className="font-mono text-xs">{text(preview.parent_page_id)}</span>} />
    {text(preview.content) ? <TextBlock value={text(preview.content)} /> : <p className="text-xs text-muted-foreground">An empty page.</p>}
  </div>
);

const DocumentPreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="File" value={<span className="font-semibold">{text(preview.file_name)}</span>} />
    <PreviewRow label="Format" value={text(preview.format_label)} />
    <PreviewRow label="Saved to" value={text(preview.destination)} />
    <div className="mt-2 rounded-xl border border-border/60 bg-background/60 px-4 py-3 max-h-80 overflow-y-auto space-y-3">
      <div>
        <p className="font-serif text-lg font-bold text-foreground">{text(preview.title)}</p>
        {text(preview.subtitle) && <p className="text-xs text-muted-foreground">{text(preview.subtitle)}</p>}
      </div>
      {list(preview.sections).map((raw, index) => {
        const section = record(raw);
        const table = record(section.table);
        return (
          <div key={index} className="space-y-1.5">
            {text(section.heading) && <p className="text-sm font-bold text-foreground">{text(section.heading)}</p>}
            {list(section.paragraphs).map((paragraph, i) => (
              <p key={i} className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                {text(paragraph)}
              </p>
            ))}
            {list(section.bullets).length > 0 && (
              <ul className="list-disc pl-5 text-sm text-foreground space-y-0.5">
                {list(section.bullets).map((bullet, i) => (
                  <li key={i}>{text(bullet)}</li>
                ))}
              </ul>
            )}
            {list(table.columns).length > 0 && (
              <DataTable
                columns={list(table.columns).map(text)}
                rows={list(table.rows).map((row) => list(row).map(text))}
              />
            )}
          </div>
        );
      })}
    </div>
  </div>
);

const QuotePreview: React.FC<{ preview: Preview }> = ({ preview }) => {
  const customer = record(preview.customer);
  const contact = [customer.contact, customer.email].map(text).filter(Boolean).join(', ');
  const currency = preview.currency;
  return (
    <div className="space-y-2 text-sm">
      <PreviewRow label="For" value={<span className="font-semibold">{text(customer.company)}</span>} />
      {contact && <PreviewRow label="Contact" value={contact} />}
      <PreviewRow label="Valid until" value={text(preview.valid_until)} />
      <DataTable
        columns={['SKU', 'Item', 'Qty', 'Unit price', 'Discount', 'Total']}
        numeric={[2, 3, 4, 5]}
        rows={list(preview.lines).map((raw) => {
          const line = record(raw);
          return [
            <span className="font-mono">{text(line.sku)}</span>,
            text(line.name),
            text(line.quantity),
            money(currency, line.unit_price),
            Number(line.discount_pct) ? `${Number(line.discount_pct)}%` : '—',
            money(currency, line.total),
          ];
        })}
      />
      <div className="flex flex-col items-end gap-0.5 text-xs pt-1">
        <span className="text-muted-foreground">Subtotal {money(currency, preview.subtotal)}</span>
        {Number(preview.discount) > 0 && <span className="text-muted-foreground">Discounts −{money(currency, preview.discount)}</span>}
        <span className="text-sm font-bold text-foreground">Total {money(currency, preview.total)}</span>
      </div>
      <PreviewRow label="Stock" value={preview.reserve_stock ? 'Reserve the quoted quantities' : 'Not reserved'} />
      <PreviewRow label="Saved to" value={`${text(preview.format_label)} in ${text(preview.destination)}`} />
      {text(preview.notes) && <PreviewRow label="Notes" value={text(preview.notes)} />}
      {list(preview.warnings).length > 0 && <Warning>{list(preview.warnings).map(text).join('; ')}</Warning>}
    </div>
  );
};

const CatalogItemPreview: React.FC<{ preview: Preview }> = ({ preview }) => {
  const item = record(preview.item);
  return (
    <div className="space-y-2 text-sm">
      <PreviewRow label="Name" value={<span className="font-semibold">{text(item.name)}</span>} />
      <PreviewRow label="Type" value={`${text(item.type)} · ${text(item.category)}${item.subcategory ? ` / ${text(item.subcategory)}` : ''}`} />
      <PreviewRow label="Status" value={text(item.status)} />
      <PreviewRow label="Discounts" value={`${text(item.min_discount_pct)}% – ${text(item.max_discount_pct)}%`} />
      {text(item.description) && <TextBlock value={text(item.description)} />}
      {list(preview.variants).length > 0 && (
        <DataTable
          columns={['SKU', 'Price']}
          numeric={[1]}
          rows={list(preview.variants).map((raw) => {
            const variant = record(raw);
            return [<span className="font-mono">{text(variant.sku)}</span>, money(variant.currency, variant.price)];
          })}
        />
      )}
    </div>
  );
};

const BeforeAfter: React.FC<{ before: unknown; after: unknown }> = ({ before, after }) => (
  <span>
    <span className="text-muted-foreground line-through decoration-muted-foreground/50">{formatValue(before)}</span>
    <span className="mx-1.5 text-muted-foreground">→</span>
    <span className="font-semibold">{formatValue(after)}</span>
  </span>
);

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.map(text).join(', ') : '(none)';
  const shown = text(value);
  return shown.length > 160 ? `${shown.slice(0, 159)}…` : shown || '(empty)';
}

const CatalogUpdatePreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="Item" value={<span className="font-semibold">{text(preview.name)}</span>} />
    {list(preview.changes).length > 0 && (
      <DataTable
        columns={['Field', 'Change']}
        rows={list(preview.changes).map((raw) => {
          const change = record(raw);
          return [text(change.field).replace(/_/g, ' '), <BeforeAfter before={change.before} after={change.after} />];
        })}
      />
    )}
    {list(preview.price_changes).length > 0 && (
      <DataTable
        columns={['SKU', 'Price']}
        rows={list(preview.price_changes).map((raw) => {
          const change = record(raw);
          return [
            <span className="font-mono">{text(change.sku)}</span>,
            <BeforeAfter before={money(change.currency, change.before)} after={money(change.currency, change.after)} />,
          ];
        })}
      />
    )}
  </div>
);

const RetirePreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="Item" value={<span className="font-semibold">{text(preview.name)}</span>} />
    <PreviewRow label="Status" value={<BeforeAfter before={preview.status} after="RETIRED" />} />
    <PreviewRow label="SKUs" value={list(preview.skus).map(text).join(', ') || 'none'} />
    <p className="text-xs text-muted-foreground">Retired items can’t be sold or quoted. Nothing is deleted.</p>
  </div>
);

const StockPreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="SKU" value={<span className="font-mono">{text(preview.sku)}</span>} />
    <PreviewRow label="Location" value={text(preview.location)} />
    <PreviewRow label="On hand" value={<BeforeAfter before={preview.before} after={preview.after} />} />
    {Number(preview.reserved) > 0 && <PreviewRow label="Reserved" value={text(preview.reserved)} />}
    <PreviewRow label="Reason" value={text(preview.reason).toLowerCase()} />
    {text(preview.note) && <PreviewRow label="Note" value={text(preview.note)} />}
  </div>
);

const ReservationPreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="SKU" value={<span className="font-mono">{text(preview.sku)}</span>} />
    <PreviewRow label="Quantity" value={text(preview.quantity)} />
    <PreviewRow label="Location" value={text(preview.location) || 'By location priority'} />
    <PreviewRow label="Available" value={text(preview.available)} />
  </div>
);

const ReleasePreview: React.FC<{ preview: Preview }> = ({ preview }) => (
  <div className="space-y-2 text-sm">
    <PreviewRow label="Reservation" value={<span className="font-mono text-xs">{text(preview.reservation_id)}</span>} />
    <p className="text-xs text-muted-foreground">The held units become available to sell again. This can’t be undone.</p>
  </div>
);

export const UndoPreview: React.FC<{
  preview: Preview;
  selected?: Set<string>;
  onToggle?: (actionId: string) => void;
}> = ({ preview, selected, onToggle }) => {
  const actions = list(preview.actions).map(record);
  const cannot = list(preview.cannot_undo).map(record);
  return (
    <div className="space-y-3 text-sm">
      {text(preview.reason) && (
        <p className="text-xs text-muted-foreground">
          <span className="font-semibold text-foreground/80">What happened:</span> {text(preview.reason)}
        </p>
      )}
      <ul className="space-y-2">
        {actions.map((action) => {
          const id = text(action.action_id);
          return (
            <li key={id} className="flex items-start gap-2.5 rounded-xl border border-border/60 bg-background/60 px-3 py-2">
              {onToggle ? (
                <input
                  type="checkbox"
                  className="mt-1 accent-primary"
                  checked={selected?.has(id) ?? true}
                  onChange={() => onToggle(id)}
                  aria-label={text(action.label)}
                />
              ) : (
                <Undo2 className="w-3.5 h-3.5 mt-1 shrink-0 text-muted-foreground" />
              )}
              <div className="min-w-0">
                <p className="font-semibold text-foreground">{text(action.label)}</p>
                {text(action.summary) && <p className="text-xs text-muted-foreground">Done earlier: {text(action.summary)}</p>}
              </div>
            </li>
          );
        })}
      </ul>
      {cannot.length > 0 && (
        <Warning>
          <p className="font-semibold">These can’t be undone and will stay as they are:</p>
          <ul className="list-disc pl-4">
            {cannot.map((item, index) => (
              <li key={index}>{text(item.summary) || text(item.tool)}</li>
            ))}
          </ul>
        </Warning>
      )}
      <p className="text-xs text-muted-foreground">Keeping them leaves everything as it is now.</p>
    </div>
  );
};

export const PreviewBody: React.FC<{ card: ApprovalCardModel }> = ({ card }) => {
  const preview = card.preview;
  switch (previewKind(card)) {
    case 'email':
      return <EmailPreview preview={preview} />;
    case 'calendar_event':
      return <CalendarPreview preview={preview} />;
    case 'slack_message':
      return <SlackPreview preview={preview} />;
    case 'notion_page':
      return <NotionPreview preview={preview} />;
    case 'document':
      return <DocumentPreview preview={preview} />;
    case 'quote':
      return <QuotePreview preview={preview} />;
    case 'catalog_item':
      return <CatalogItemPreview preview={preview} />;
    case 'catalog_update':
      return <CatalogUpdatePreview preview={preview} />;
    case 'catalog_retire':
      return <RetirePreview preview={preview} />;
    case 'stock_change':
      return <StockPreview preview={preview} />;
    case 'stock_reservation':
      return <ReservationPreview preview={preview} />;
    case 'stock_release':
      return <ReleasePreview preview={preview} />;
    case 'undo':
      return <UndoPreview preview={preview} />;
    default:
      return (
        <pre className="rounded-xl border border-border/60 bg-background/60 p-3 text-xs overflow-x-auto">
          {JSON.stringify(preview, null, 2)}
        </pre>
      );
  }
};
