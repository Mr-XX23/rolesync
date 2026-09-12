import {
  Archive,
  Boxes,
  BriefcaseBusiness,
  CalendarPlus,
  Handshake,
  FileText,
  Mail,
  MessageSquare,
  Package,
  PackageMinus,
  PackagePlus,
  Receipt,
  ShieldCheck,
  Undo2,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ApprovalCardModel } from './chatState';

/** The kind of action a card is about (set by the engine's preview). */
export function previewKind(card: ApprovalCardModel): string {
  const kind = card.preview.kind;
  if (typeof kind === 'string' && kind) {
    return kind;
  }
  return card.tool === 'send_email' ? 'email' : 'generic';
}

const KINDS: Record<string, { title: string; approve: string; icon: LucideIcon }> = {
  email: { title: 'Send this email?', approve: 'Approve & send', icon: Mail },
  calendar_event: { title: 'Create this calendar event?', approve: 'Approve & create', icon: CalendarPlus },
  slack_message: { title: 'Post this Slack message?', approve: 'Approve & post', icon: MessageSquare },
  notion_page: { title: 'Create this Notion page?', approve: 'Approve & create', icon: FileText },
  document: { title: 'Create this document?', approve: 'Approve & create', icon: FileText },
  quote: { title: 'Create this quote?', approve: 'Approve & create', icon: Receipt },
  deal_create: { title: 'Create this deal?', approve: 'Approve & create', icon: Handshake },
  deal_update: { title: 'Update this deal?', approve: 'Approve & update', icon: BriefcaseBusiness },
  catalog_item: { title: 'Add this item to the catalog?', approve: 'Approve & add', icon: PackagePlus },
  catalog_update: { title: 'Update this catalog item?', approve: 'Approve & update', icon: Package },
  catalog_retire: { title: 'Retire this catalog item?', approve: 'Approve & retire', icon: Archive },
  stock_change: { title: 'Change this stock level?', approve: 'Approve & change', icon: Boxes },
  stock_reservation: { title: 'Reserve this stock?', approve: 'Approve & reserve', icon: PackagePlus },
  stock_release: { title: 'Release this reservation?', approve: 'Approve & release', icon: PackageMinus },
  undo: { title: 'Undo these actions?', approve: 'Undo them', icon: Undo2 },
};

export function describeKind(card: ApprovalCardModel): { title: string; approve: string; icon: LucideIcon } {
  return KINDS[previewKind(card)] ?? { title: `Allow ${card.tool}?`, approve: 'Approve', icon: ShieldCheck };
}
