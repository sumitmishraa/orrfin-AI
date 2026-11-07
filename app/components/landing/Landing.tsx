'use client';
import { ElementType, ReactNode, useEffect, useRef, useState } from 'react';

const reduced = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Entrance: content renders visible; only elements still below the fold wait, then rise in. */
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

/* ---------------- Hero: slow crossfade of goods moving through Indian markets ---------------- */
const HERO = [
  { src: '/landing/photos/goods-carrier-crawford-market-mumbai-405400495.jpg', alt: 'A handcart of labelled cartons being pulled through traffic outside Crawford Market, Mumbai' },
  { src: '/landing/photos/crawford-market-in-mumbai-2.jpg', alt: 'A fruit stall stacked on plastic crates inside Crawford Market, Mumbai' },
  { src: '/landing/photos/banana-stand-crawford-market-mumbai-393521492.jpg', alt: 'A banana seller serving customers at Crawford Market, Mumbai' },
];

export function HeroMedia() {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (reduced()) return;
    const id = setInterval(() => { if (!document.hidden) setN((v) => (v + 1) % HERO.length); }, 6000);
    return () => clearInterval(id);
  }, []);
  return (
    <>
      <div className="ol-hero-media">
        {HERO.map((p, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={p.src} src={p.src} alt={i === n ? p.alt : ''} aria-hidden={i !== n} className={i === n ? 'on' : ''} width={1920} height={1280} fetchPriority={i === 0 ? 'high' : 'low'} loading={i === 0 ? 'eager' : 'lazy'} decoding="async" />
        ))}
        <div className="ol-hero-scrim" />
      </div>
      <p className="ol-pin" style={{ opacity: n === 0 ? 1 : 0 }} aria-hidden={n !== 0}>Every carton here is a PO line, a goods receipt and a bill.</p>
    </>
  );
}

/* ---------------- The board: purchase orders across ten hubs ---------------- */
type Row = { po: string; supplier: string; hub: string; amount: string; gst: string; status: string; tone: string; detail: string };
const ROWS: Row[] = [
  { po: 'PO/PUN/2026-27/000137', supplier: 'Deccan Agencies', hub: 'Pune', amount: '₹86,730', gst: 'CGST + SGST', status: 'Awaiting delivery', tone: 'issued', detail: 'Issued 3 Nov to the Viman Nagar dark store. Needed by 10 Nov. Zoho Books received the PO within minutes of issue.' },
  { po: 'PO/KOL/2026-27/000127', supplier: 'Godavari Tech', hub: 'Kolkata', amount: '₹34,250', gst: 'IGST', status: 'Exception', tone: 'exception', detail: 'Rider rain jackets billed at ₹810.38 against a PO rate of ₹764.51: 6% over the 2% tolerance. Payment is blocked until accounts payable resolves it.' },
  { po: 'PO/BLR/2026-27/000119', supplier: 'Satpura Supplies', hub: 'Bengaluru', amount: '₹1,12,400', gst: 'IGST', status: 'Part received', tone: 'partial', detail: 'Koramangala recorded 60 of 100 cold-chain gel packs. The remaining 40 stay open; billing for more than 60 is refused.' },
  { po: 'PO/PUN/2026-27/000418', supplier: 'Deccan Packaging Industries', hub: 'Pune', amount: '₹58,528', gst: 'CGST + SGST', status: 'Exception', tone: 'exception', detail: 'Invoice DPI/2026/1187 bills 100 insulated bags; the store received 80. ₹9,912 is held until the supplier sends a credit note. Everything else on the invoice matches.' },
  { po: 'PO/HYD/2026-27/000125', supplier: 'Ganga Safety', hub: 'Hyderabad', amount: '₹29,044', gst: 'IGST', status: 'Matched', tone: 'done', detail: 'PO, goods receipt and invoice agree line by line. A second person approved payment and the bill is queued for the ERP.' },
  { po: 'PO/DEL/2026-27/000139', supplier: 'Thar Cold Chain', hub: 'Delhi', amount: '₹1,46,870', gst: 'IGST', status: 'On hold', tone: 'hold', detail: 'Supplier risk is critical: late on 39% of deliveries and an expired insurance certificate. New POs and payments are blocked until the risk manager releases the hold.' },
  { po: 'PO/MUM/2026-27/000130', supplier: 'Kosi Cold Chain', hub: 'Mumbai', amount: '₹2,07,315', gst: 'CGST + SGST', status: 'In Tally', tone: 'done', detail: 'Matched, approved and posted to Tally Prime through the relay on the finance PC. One voucher, even though the first send timed out.' },
  { po: 'PO/AHM/2026-27/000130', supplier: 'Satpura Logistics', hub: 'Ahmedabad', amount: '₹64,210', gst: 'IGST', status: 'Awaiting delivery', tone: 'issued', detail: 'Awarded from RFQ/AHM/2026-27/000004 to the best eligible bid: 4-day lead time and 96% on-time history from your own receipts.' },
  { po: 'PO/CHE/2026-27/000091', supplier: 'Chola Packaging', hub: 'Chennai', amount: '₹41,200', gst: 'IGST', status: 'Paid', tone: 'done', detail: 'Paid on 45-day terms and recorded by accounts payable. Orrfin.ai tracks payment status; it never moves money itself.' },
];

export function Board() {
  const [open, setOpen] = useState(3);
  return (
    <div className="ol-rows" data-ui>
      {ROWS.map((r, i) => (
        <button key={r.po} type="button" className={`ol-row ${i === open ? 'open' : ''}`} aria-expanded={i === open} onClick={() => setOpen(i)}>
          <span>{r.po}</span>
          <span className="fact">{r.hub}</span>
          <span className="fact">{r.gst}</span>
          <span className="fact" style={{ textAlign: 'right' }}>{r.amount}</span>
          <span className={`st st-${r.tone}`}>{r.status}</span>
          {i === open && <span className="detail"><b style={{ display: 'block', fontSize: 22, letterSpacing: '-0.02em', marginBottom: 6 }}>{r.supplier}</b>{r.detail}</span>}
        </button>
      ))}
    </div>
  );
}

/* ---------------- Try the rules: one PO the visitor operates ---------------- */
const rupee = (n: number) => '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function Rules() {
  const [branch, setBranch] = useState<'PUN' | 'BLR'>('PUN');
  const [received, setReceived] = useState(80);
  const [billedAll, setBilledAll] = useState(true);
  const [risk, setRisk] = useState<'low' | 'high' | 'critical'>('low');
  const [paid, setPaid] = useState(false);
  const [note, setNote] = useState('');

  const intra = branch === 'PUN';
  const billed = billedAll ? 100 : received;
  const taxable = billed * 420 + 200 * 38;
  const tax = Math.round(taxable * 0.18 * 100) / 100;
  const exception = billed > received;
  const held = Math.round((billed - received) * 420 * 1.18 * 100) / 100;
  const hold = risk === 'critical';
  const blocked = exception || hold;
  const route = ['Hub manager', 'Head of procurement', ...(risk !== 'low' ? ['Risk manager'] : [])];
  const reset = () => { setPaid(false); setNote(''); };

  function pay() {
    if (hold) { setPaid(false); setNote('Refused: the supplier is on hold. The database rejects the payment, whoever asks.'); return; }
    if (exception) { setPaid(false); setNote(`Refused: ${billed - received} bags are billed but not received. Resolve the exception first.`); return; }
    setPaid(true); setNote(`Approved by a second person. ${rupee(taxable + tax)} is posted to Tally Prime as one voucher.`);
  }

  return (
    <section className="ol-rules" id="rules" aria-labelledby="rules-h">
      <div className="ol-rules-stage">
        <article className="ol-po" data-ui aria-live="polite" aria-label="Sample purchase order">
          <header>
            <div><strong>Purchase order</strong><em>{intra ? 'PO/PUN/2026-27/000418' : 'PO/BLR/2026-27/000612'}</em></div>
            <div className="co">Kirnova Quick Commerce<br />GSTIN {intra ? '27AAKCK7421Q1ZU' : '29AAKCK7421Q1ZQ'}<br />{intra ? 'Viman Nagar, Pune' : 'Indiranagar, Bengaluru'}</div>
          </header>
          <p style={{ marginTop: 8, color: 'var(--muted)', fontSize: 12.5 }}>Supplier Deccan Packaging Industries, GSTIN 27AADCD4829K1ZE, Maharashtra</p>
          <table>
            <thead><tr><th>Item</th><th className="n">Qty</th><th className="n">Rate</th><th className="n">Amount</th></tr></thead>
            <tbody>
              <tr><td>Insulated delivery bag, 40 L<span className={`sub ${exception ? 'bad' : ''}`}>Received {received} of 100, billed {billed}</span></td><td className="n">{billed}</td><td className="n">₹420.00</td><td className="n">{rupee(billed * 420)}</td></tr>
              <tr><td>Thermal liner pack<span className="sub">Received 200 of 200</span></td><td className="n">200</td><td className="n">₹38.00</td><td className="n">₹7,600.00</td></tr>
            </tbody>
          </table>
          <dl>
            <dt>Taxable</dt><dd>{rupee(taxable)}</dd>
            {intra ? <><dt>CGST 9%</dt><dd>{rupee(tax / 2)}</dd><dt>SGST 9%</dt><dd>{rupee(tax / 2)}</dd></> : <><dt>IGST 18%</dt><dd>{rupee(tax)}</dd></>}
            <dt className="tot">{exception ? 'Billed' : 'Payable'}</dt><dd className="tot">{rupee(taxable + tax)}</dd>
          </dl>
          <p className="route">Approval route: {route.join(', then ')}.</p>
          <div className="ol-stamps" aria-hidden>
            <span key={`grn-${received}`} className="ol-stamp" style={{ color: 'var(--slate)', bottom: '20px', left: '6%', '--r': '-5deg' } as React.CSSProperties}>GRN {received} / 100<small>{intra ? 'Viman Nagar' : 'Indiranagar'}</small></span>
            {exception
              ? <span key={`ex-${held}`} className="ol-stamp" style={{ color: 'var(--red)', bottom: '22px', right: '6%', '--r': '-8deg' } as React.CSSProperties}>Exception<small>{rupee(held)} held</small></span>
              : <span key="match" className="ol-stamp" style={{ color: 'var(--slate)', bottom: '22px', right: '6%', '--r': '4deg' } as React.CSSProperties}>Matched<small>PO, GRN and bill agree</small></span>}
            {hold && <span key="hold" className="ol-stamp" style={{ color: 'var(--maroon)', top: '14%', left: '30%', '--r': '7deg' } as React.CSSProperties}>On hold<small>Critical supplier risk</small></span>}
            {paid && !blocked && <span key="tally" className="ol-stamp" style={{ color: 'var(--ink)', top: '14%', left: '32%', '--r': '-3deg' } as React.CSSProperties}>Posted to Tally<small>One voucher</small></span>}
          </div>
        </article>
      </div>
      <div className="ol-rules-text">
        <h2 id="rules-h">Change the order. Watch the rules.</h2>
        <Reveal className="ol-block">
          <h3>Pick the branch. The tax follows.</h3>
          <p>The supplier is in Maharashtra. Buying for Pune is intra-state, so it is CGST plus SGST; for Bengaluru it becomes IGST, under Karnataka&rsquo;s GSTIN and the next number in that branch&rsquo;s series.</p>
          <div className="ol-seg-ctl" role="group" aria-label="Branch">
            <button type="button" aria-pressed={branch === 'PUN'} onClick={() => { setBranch('PUN'); reset(); }}>Pune</button>
            <button type="button" aria-pressed={branch === 'BLR'} onClick={() => { setBranch('BLR'); reset(); }}>Bengaluru</button>
          </div>
        </Reveal>
        <Reveal className="ol-block">
          <h3>Count what actually arrived.</h3>
          <p>The store records a goods receipt for what came off the van. Receiving more than was ordered is refused.</p>
          <label className="ol-range">Bags received: <b>{received} of 100</b>
            <input type="range" min={0} max={100} step={10} value={received} onChange={(e) => { setReceived(Number(e.target.value)); reset(); }} />
          </label>
        </Reveal>
        <Reveal className="ol-block">
          <h3>Read the supplier&rsquo;s bill.</h3>
          <p>The invoice PDF is read, a person confirms it, and every line is matched against the PO and the receipts.</p>
          <div className="ol-seg-ctl" role="group" aria-label="What the supplier billed">
            <button type="button" aria-pressed={billedAll} onClick={() => { setBilledAll(true); reset(); }}>Billed all 100 bags</button>
            <button type="button" aria-pressed={!billedAll} onClick={() => { setBilledAll(false); reset(); }}>Billed what arrived</button>
          </div>
          <p className="result">{exception ? `Exception: billed ${billed}, received ${received}. ${rupee(held)} is held.` : 'Matched within tolerance.'}</p>
        </Reveal>
        <Reveal className="ol-block">
          <h3>Score the supplier.</h3>
          <p>Risk comes from your own deliveries, invoices and documents. High risk adds an approver; critical risk places a hold.</p>
          <div className="ol-seg-ctl" role="group" aria-label="Supplier risk">
            {(['low', 'high', 'critical'] as const).map((r) => <button key={r} type="button" aria-pressed={risk === r} onClick={() => { setRisk(r); reset(); }}>{r[0].toUpperCase() + r.slice(1)}</button>)}
          </div>
        </Reveal>
        <Reveal className="ol-block">
          <h3>Pay, or be told why not.</h3>
          <p>A second person approves. If anything above is wrong, the database refuses, even for an admin or a script.</p>
          <div><button type="button" className="ol-btn" onClick={pay}>Approve payment</button></div>
          {note && <p className="result" role="status">{note}</p>}
        </Reveal>
      </div>
    </section>
  );
}

/* ---------------- Refusals: cards that fold into spines ---------------- */
const REFUSALS = [
  { t: 'Approving your own request', d: 'The approver of every step is checked against the requester inside the database, so no screen, import or API call can skip it.', w: 'Database rule' },
  { t: 'Receiving more than was ordered', d: 'A goods receipt that takes a line past its ordered quantity is refused when it is saved.', w: 'Database rule' },
  { t: 'Billing more than was received', d: 'Three-way matching blocks payment until billed equals received, line by line.', w: 'Database rule' },
  { t: 'Paying a supplier on hold', d: 'Critical risk places a hold. New POs and payments to that supplier fail until it is released.', w: 'Database rule' },
  { t: 'Gaps in PO numbers', d: 'Numbers run per branch and fiscal year, like PO/BLR/2026-27/000123, and stay gapless under 50 parallel issues.', w: 'Tested under load' },
  { t: 'One company seeing another', d: 'Every table has row-level security keyed to the organization; the API cannot switch it off.', w: 'Database rule' },
  { t: 'AI acting on its own', d: 'The concierge reads with your permissions and cites its sources. It can draft a request; only a person submits.', w: 'By design' },
  { t: 'The same bill in Tally twice', d: 'An idempotent outbox means a lost response and a retry still produce one voucher.', w: 'Tested with outages' },
];

export function Spines() {
  const wrap = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  useEffect(() => {
    const onScroll = () => {
      const el = wrap.current;
      if (!el || window.innerWidth <= 900) return;
      const r = el.getBoundingClientRect();
      const span = r.height - window.innerHeight;
      const p = Math.min(1, Math.max(0, -r.top / span));
      setActive(Math.min(REFUSALS.length - 1, Math.floor(p * REFUSALS.length)));
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  function jump(i: number) {
    const el = wrap.current;
    if (!el) return;
    const top = el.getBoundingClientRect().top + window.scrollY;
    const span = el.offsetHeight - window.innerHeight;
    window.scrollTo({ top: top + (span * (i + 0.5)) / REFUSALS.length, behavior: reduced() ? 'auto' : 'smooth' });
  }
  return (
    <section className="ol-spines" id="refusals" ref={wrap} aria-labelledby="ref-h">
      <div className="ol-spines-stage">
        <h2 id="ref-h">What Orrfin.ai refuses to do</h2>
        <div className="ol-deck">
          {REFUSALS.map((c, i) => {
            const state = i < active ? 'spine' : i > active ? 'ahead' : '';
            return (
              <button key={c.t} type="button" className={`ol-sp ${state}`} style={{ width: state === 'spine' ? 96 : state === 'ahead' ? 0 : 620 }} onClick={() => (i === active ? null : jump(i))} aria-label={c.t} tabIndex={state === 'ahead' ? -1 : 0}>
                <h3>{c.t}</h3>
                <p>{c.d}</p>
                <footer><span>{c.w}</span><span>{i + 1} of {REFUSALS.length}</span></footer>
              </button>
            );
          })}
        </div>
        <p className="ol-deck-foot"><span>Eight rules, enforced in the database or by design.</span><a href="/demo">Try to break one in the demo</a></p>
      </div>
    </section>
  );
}

/* ---------------- Close: the street clip ---------------- */
export function StreetClip() {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (reduced()) { v.pause(); return; }
    v.play().catch(() => undefined);
  }, []);
  return <video ref={ref} muted loop playsInline preload="metadata" poster="/landing/photos/street-in-mumbai-video-01-poster.jpg" aria-label="A Mumbai street at dusk, traffic and shops below new towers"><source src="/landing/photos/street-in-mumbai-video-01.webm" type="video/webm" /></video>;
}
