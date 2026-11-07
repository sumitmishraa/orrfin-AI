'use client';
/* Client pieces of the landing page: scroll entrances and the tabbed product screens. */
import { ElementType, ReactNode, useEffect, useRef, useState } from 'react';

const reduced = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Entrance: content renders visible; only elements still below the fold wait, then fade up. */
export function Reveal({ as: Tag = 'div', i = 0, className = '', children, ...rest }: { as?: ElementType; i?: number; className?: string; children: ReactNode; [key: string]: unknown }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || reduced() || el.getBoundingClientRect().top < window.innerHeight * 0.9) return;
    el.classList.add('rv-wait');
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { el.classList.remove('rv-wait'); io.disconnect(); }
    }, { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return <Tag ref={ref} className={`rv ${className}`} style={{ '--i': i } as React.CSSProperties} {...rest}>{children}</Tag>;
}

const SCREENS = [
  {
    key: 'match', tab: 'Invoice matching', img: '/landing/ui/invoice-match.jpg', path: 'app/invoices',
    title: 'Every bill checked against the PO and what arrived',
    text: 'Accounts payable uploads the supplier’s PDF. Orrfin.ai reads it, a person confirms the fields, and each line is matched against the purchase order and the goods receipts.',
    points: ['Overbilling and price changes are flagged as exceptions', 'Payment stays blocked until blocking exceptions are resolved', 'A second person approves before the bill goes to the ERP'],
  },
  {
    key: 'review', tab: 'Invoice review', img: '/landing/ui/invoice-review.jpg', path: 'app/invoices/review',
    title: 'The original document beside the fields read from it',
    text: 'Scans and PDFs are read automatically. Each field shows how confident the reader is, so the reviewer knows exactly what to check.',
    points: ['Works on PDFs and scanned images', 'Nothing is matched until a person confirms it', 'GSTINs, CGST/SGST and IGST captured per invoice'],
  },
  {
    key: 'sourcing', tab: 'Sourcing', img: '/landing/ui/sourcing.jpg', path: 'app/sourcing',
    title: 'RFQs ranked on price, lead time, risk and real history',
    text: 'Procurement invites suppliers through private links. Bids are compared on total including GST, lead time, supplier risk and delivery history from your own receipts.',
    points: ['Suppliers bid without creating an account', 'Ineligible bids are explained, not hidden', 'Awarding a bid creates the purchase order'],
  },
  {
    key: 'risk', tab: 'Supplier risk', img: '/landing/ui/risk.jpg', path: 'app/risk',
    title: 'Risk scores you can explain, holds you can’t bypass',
    text: 'Scores come from onboarding checks, documents, delivery, quality and invoice accuracy. High risk adds an approver; critical risk places a hold the database enforces.',
    points: ['Every point in a score has evidence', 'Holds block new POs and payments', 'Unverified checks are shown as “not performed”'],
  },
  {
    key: 'overview', tab: 'Spend overview', img: '/landing/ui/overview.jpg', path: 'app',
    title: 'One view of spend across every branch',
    text: 'Monthly spend, spend by branch and category, top suppliers and the alerts that need attention: renewals, expiring certificates and overdue approvals.',
    points: ['Each figure links to the records behind it', 'Branch users see only their branches', 'Alerts come from a background scan every few minutes'],
  },
];

export function Screens() {
  const [key, setKey] = useState(SCREENS[0].key);
  const s = SCREENS.find((x) => x.key === key)!;
  return (
    <div>
      <div className="ol-tabs" role="tablist" aria-label="Product screens">
        {SCREENS.map((x) => (
          <button key={x.key} id={`tab-${x.key}`} role="tab" aria-selected={x.key === key} aria-controls="screen-panel" onClick={() => setKey(x.key)}>{x.tab}</button>
        ))}
      </div>
      <div className="ol-screen ol-fade" key={s.key} id="screen-panel" role="tabpanel" aria-labelledby={`tab-${s.key}`}>
        <div className="ol-screen-copy">
          <h3>{s.title}</h3>
          <p>{s.text}</p>
          <ul>{s.points.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
        <div className="ol-frame">
          <div className="ol-frame-bar"><i /><i /><i /><span>orrfin.ai/{s.path}</span></div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={s.img} alt={s.title} width={1600} height={1025} loading="lazy" decoding="async" />
        </div>
      </div>
    </div>
  );
}
