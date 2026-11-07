import type { Metadata } from 'next';
import localFont from 'next/font/local';
import Image from 'next/image';
import './landing.css';
import { Board, HeroMedia, Reveal, Rules, Spines, StreetClip } from './components/landing/Landing';

const switzer = localFont({
  src: [
    { path: './fonts/switzer-400.woff2', weight: '400' },
    { path: './fonts/switzer-500.woff2', weight: '500' },
    { path: './fonts/switzer-600.woff2', weight: '600' },
  ],
  variable: '--font-switzer',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Orrfin.ai: procurement for multi-branch businesses in India',
  description: 'Requests, approvals, purchase orders, goods receipts and invoice matching for every branch, posted to Tally or Zoho Books, with the rules enforced in the database.',
};

// Real stage lengths for one dark-store purchase: minutes to ask, a day to approve, four days to deliver, a minute to match.
const WEEK = [
  { when: 'Two minutes', grow: 12, tone: 'var(--bg)', clause: 'First, a store lead asks for 100 bags; budget and price are checked as they type.' },
  { when: 'About a day', grow: 15, tone: 'var(--mustard)', clause: 'Then the hub manager and procurement approve in order, within a 24-hour SLA.' },
  { when: 'Four days with the supplier', grow: 61, tone: '#f3c9c9', clause: 'Next, the supplier delivers and the store records exactly what arrived.' },
  { when: 'Under a minute', grow: 12, tone: 'var(--surface)', clause: 'Last, the bill is read, matched to the PO and receipt, and posted to Tally.' },
];

const PRODUCTS: { name: string; line: string; tone: string }[] = [
  { name: 'Intake-to-Procure', line: 'Every branch request, with budget and price checked before anyone approves.', tone: 't-red' },
  { name: 'Approvals', line: 'Routed by branch, amount, category and supplier risk. Nobody approves their own.', tone: 't-maroon' },
  { name: 'Sourcing', line: 'RFQs through private supplier links, ranked on total, lead time and delivery history.', tone: 't-mustard' },
  { name: 'Procure-to-Pay', line: 'GST-correct POs, goods receipts and supplier invoices matched line by line.', tone: 't-slate' },
  { name: 'Supplier onboarding', line: 'GSTIN, PAN, bank details and certificates, checked before the first payment.', tone: 't-ink' },
  { name: 'Risk orchestration', line: 'Scores with evidence. Critical risk places a hold the database enforces.', tone: 't-red' },
  { name: 'Contracts', line: 'Generated from your clause library, reviewed clause by clause, renewals tracked.', tone: 't-mustard' },
  { name: 'AI concierge', line: 'Questions answered from your records, with citations. It drafts; people submit.', tone: 't-maroon' },
  { name: 'ERP push', line: 'Issued POs and approved bills reach Zoho Books or Tally Prime exactly once.', tone: 't-slate' },
  { name: 'One purchase record', line: 'All nine share one trail: who asked, who approved, what arrived and what was paid.', tone: 't-ink' },
];

const SHOTS = [
  { src: '/landing/ui/invoice-match.jpg', alt: 'Orrfin.ai three-way match: ordered, received and billed quantities with a blocking price exception', at: 1, pos: '40% 100%' },
  { src: '/landing/ui/sourcing.jpg', alt: 'Orrfin.ai RFQ bid comparison ranking suppliers by total, lead time, risk and delivery history', at: 4, pos: '100% 100%' },
  { src: '/landing/ui/risk.jpg', alt: 'Orrfin.ai supplier risk register with high-risk suppliers and active payment holds', at: 8, pos: '0% 30%' },
];

const PROOF = [
  ['Built for', 'Quick-commerce dark stores', 'Restaurant and cloud-kitchen chains', 'Pharmacy and retail chains', 'Multi-plant manufacturers', 'Companies with several GSTINs'],
  ['Connects to', 'Tally Prime, through a local relay', 'Zoho Books', 'Google Gemini', 'Anthropic Claude', 'Hindsight supplier memory'],
  ['Handles India', 'CGST and SGST within a state', 'IGST between states', 'Place of supply on every PO', 'HSN codes on every line', 'PO numbers per branch and year', 'GSTIN checksum checks'],
  ['Proven by', 'End-to-end tests in Docker', 'Row-level security on every table', 'Gapless numbers under 50 parallel issues', 'ERP outages and lost responses', 'A fictional company with a year of history'],
];

export default function Home() {
  const mosaic: React.ReactNode[] = [];
  PRODUCTS.forEach((p, i) => {
    const shot = SHOTS.find((s) => s.at === i);
    if (shot) mosaic.push(<Reveal key={shot.src} className="ol-shot" i={i % 4}><Image src={shot.src} alt={shot.alt} width={1600} height={1025} sizes="(max-width: 560px) 100vw, 50vw" style={{ objectPosition: shot.pos }} /></Reveal>);
    mosaic.push(<Reveal key={p.name} className={`ol-tile ${p.tone}`} i={i % 4}><h3>{p.name}</h3><p>{p.line}</p></Reveal>);
  });

  return (
    <main className={`ol ${switzer.variable}`}>
      <section className="ol-hero" aria-labelledby="hero-h">
        <HeroMedia />
        <nav className="ol-nav" aria-label="Site">
          <a href="/" className="ol-word">orrfin.ai</a>
          <div className="ol-nav-right">
            <a href="#products">Products</a>
            <a href="#rules">Try the rules</a>
            <a href="/login">Sign in</a>
            <a href="/demo" className="ol-btn">Open the live demo</a>
          </div>
        </nav>
        <div className="ol-hero-copy">
          <h1 id="hero-h">Every branch buys.<br />One team pays.</h1>
          <p>Orrfin.ai is procurement for Indian multi-branch businesses: requests, approvals, POs, receipts and invoice matching, posted to Tally or Zoho Books.</p>
          <a href="/demo" className="ol-btn">Open the live demo</a>
        </div>
        <div className="ol-cards">
          <a className="ol-card" href="#rules"><Image src="/landing/ui/invoice-review.jpg" alt="An invoice PDF beside its extracted, confirmed fields" width={1600} height={1025} sizes="230px" priority /><span>Invoice review <span aria-hidden>↓</span></span></a>
          <a className="ol-card" href="#products"><Image src="/landing/ui/overview.jpg" alt="Spend overview across ten hubs" width={1600} height={1025} sizes="230px" priority /><span>Spend overview <span aria-hidden>↓</span></span></a>
        </div>
      </section>

      <Reveal as="section" className="ol-week" aria-labelledby="week-h">
        <h2 id="week-h">Where a purchase spends its week</h2>
        <div className="ol-bar" data-ui>
          {WEEK.map((s, i) => <div key={s.when} className="ol-seg" style={{ flexGrow: s.grow, flexBasis: 0, background: s.tone, '--i': i } as React.CSSProperties}><b>{s.when}</b></div>)}
        </div>
        <div className="ol-clauses">
          {WEEK.map((s) => <div key={s.when} style={{ flexGrow: s.grow, flexBasis: 0, minWidth: 0 }}><p>{s.clause}</p></div>)}
        </div>
      </Reveal>

      <section className="ol-board" aria-labelledby="board-h">
        <div className="ol-board-head">
          <h2 id="board-h">Ten hubs, one board</h2>
          <p>Purchase orders from the demo company. Open any row to see why it is where it is.</p>
        </div>
        <Board />
        <p className="ol-board-note">Kirnova Quick Commerce is fictional; its numbers come from the demo you can sign in to.</p>
      </section>

      <Rules />

      <section id="products" aria-labelledby="products-h">
        <div className="ol-products-head">
          <h2 id="products-h">Nine products. One purchase record.</h2>
          <p>Each hands its work to the next, so the request, its approvals, the PO, the receipt and the bill are one trail instead of five spreadsheets.</p>
        </div>
        <div className="ol-mosaic">{mosaic}</div>
      </section>

      <section className="ol-proof" aria-labelledby="proof-h">
        <h2 id="proof-h">What it&rsquo;s built on</h2>
        <div className="ol-proof-cols">
          {PROOF.map(([kind, ...names]) => <ul key={kind}><li>{kind}</li>{names.map((n) => <li key={n}>{n}</li>)}</ul>)}
        </div>
      </section>

      <Spines />

      <section aria-labelledby="close-h">
        <div className="ol-strip">
          <Image src="/landing/photos/kirana-shop.jpg" alt="A neighbourhood kirana store with crates of rice stacked outside" width={1600} height={1063} sizes="33vw" />
          <StreetClip />
          <Image src="/landing/photos/india-koyambedu-market-onions-08-3987045248.jpg" alt="Red onions heaped at Koyambedu Market, Chennai" width={1920} height={1440} sizes="33vw" />
        </div>
        <div className="ol-close">
          <div>
            <h2 id="close-h" className="sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>Try the demo</h2>
            <p className="big">Run one purchase from a dark store to Tally yourself, no sign-up needed: <a href="/demo">pick anyone in the company</a> and follow it end to end.</p>
            <div className="small">
              <p>Kirnova Quick Commerce is a fictional operator with 10 hubs, 58 dark stores, about 150 suppliers and a year of history.</p>
              <p>Each role sees its own screens and can do only what that job allows.</p>
            </div>
          </div>
          <ul className="roles" aria-label="Roles in the demo">
            <li>Store lead</li><li>Hub manager</li><li>Head of procurement</li><li>Accounts payable</li><li>Legal</li><li>Risk</li><li>Admin</li>
          </ul>
        </div>
      </section>

      <footer className="ol-foot">
        <div className="ol-foot-cols">
          <ul><li>Product</li><li><a href="#rules">Try the rules</a></li><li><a href="#products">Nine products</a></li><li><a href="#refusals">What it refuses</a></li></ul>
          <ul><li>Demo</li><li><a href="/demo">Open the live demo</a></li><li><a href="/login">Sign in with an account</a></li><li><a href="/signup">Create an organization</a></li></ul>
          <ul><li>Source</li><li><a href="https://github.com/sumitmishraa/vendormind" rel="noopener noreferrer">GitHub repository</a></li></ul>
          <ul><li>Legal</li><li><a href="/privacy">Privacy</a></li><li><a href="/terms">Terms</a></li></ul>
        </div>
        <div />
        <div>
          <svg viewBox="0 0 1000 205" role="img" aria-label="orrfin.ai"><text x="0" y="170" fontSize="230" textLength="1000" lengthAdjust="spacingAndGlyphs">orrfin.ai</text></svg>
          <p className="ol-credits">Photographs and footage, via Wikimedia Commons: <a href="https://commons.wikimedia.org/w/index.php?curid=58861993">Goods Carrier, Crawford Market</a> and <a href="https://commons.wikimedia.org/w/index.php?curid=58861968">Banana Stand, Crawford Market</a> by David Brossard (CC BY-SA 2.0); <a href="https://commons.wikimedia.org/wiki/File:Crawford_Market_in_Mumbai_2.jpg">Crawford Market in Mumbai 2</a> by Dudva (CC0); <a href="https://commons.wikimedia.org/w/index.php?curid=24292781">Kirana shop</a> by Renzilde (CC BY-SA 3.0); <a href="https://commons.wikimedia.org/w/index.php?curid=23465754">Koyambedu Market, Onions</a> by McKay Savage (CC BY 2.0); <a href="https://commons.wikimedia.org/wiki/File:Street_in_Mumbai_(video)_01.webm">Street in Mumbai</a> by Nicolas Vigier (CC0). Product screens are from the Orrfin.ai demo.</p>
          <p className="ol-legal">© {new Date().getFullYear()} Orrfin.ai. Kirnova Quick Commerce and every supplier in the demo are fictional.</p>
        </div>
      </footer>
    </main>
  );
}
