import type { Metadata } from 'next';
import { Bot, Boxes, CheckCircle2, ClipboardCheck, FileSignature, FileText, Inbox, Network, ShieldAlert, Users } from 'lucide-react';
import './landing.css';
import { Reveal, Screens } from './components/landing/Landing';

export const metadata: Metadata = {
  title: 'Orrfin.ai: procurement for multi-branch businesses in India',
  description: 'Requests, approvals, purchase orders, goods receipts and invoice matching for every branch, posted to Tally or Zoho Books, with the rules enforced in the database.',
};

// A real sequence, shown as an ordered list: who does what, from request to payment.
const FLOW = [
  { who: 'Store lead', what: 'Request', text: 'Asks for what the branch needs. Budget and price are checked on submit.' },
  { who: 'Managers', what: 'Approve', text: 'Approvals route by branch, amount, category and supplier risk.' },
  { who: 'Procurement', what: 'Order', text: 'Issues a GST-correct PO, or runs an RFQ and awards the best bid.' },
  { who: 'Store', what: 'Receive', text: 'Records what actually arrived. Over-receipt is refused.' },
  { who: 'Accounts payable', what: 'Match and pay', text: 'Matches the bill to the PO and receipt, then posts it to the ERP.' },
];

const PRODUCTS = [
  { icon: Inbox, name: 'Intake-to-Procure', text: 'One place for every branch request, with budget and price checks before approval.' },
  { icon: ClipboardCheck, name: 'Approvals', text: 'Multi-step routing with SLAs. Nobody can approve their own request.' },
  { icon: Boxes, name: 'Sourcing', text: 'RFQs through private supplier links, with bids ranked on total, lead time and history.' },
  { icon: FileText, name: 'Procure-to-Pay', text: 'Gapless PO numbers, goods receipts, invoice reading and three-way matching.' },
  { icon: Users, name: 'Supplier onboarding', text: 'A portal for GSTIN, PAN, bank details and certificates, with automatic checks.' },
  { icon: ShieldAlert, name: 'Risk orchestration', text: 'Explainable supplier scores. Critical risk places a hold on POs and payments.' },
  { icon: FileSignature, name: 'Contracts', text: 'Generate from your clause library, review supplier versions, track renewals.' },
  { icon: Bot, name: 'AI concierge', text: 'Plain-language questions answered from your records, with citations.' },
  { icon: Network, name: 'ERP push', text: 'Issued POs and approved bills sent to Zoho Books or Tally Prime, exactly once.' },
];

const RULES = [
  { title: 'No self-approval', text: 'The approver of every step is checked against the requester in the database, even for API calls and imports.', where: 'Database rule' },
  { title: 'No over-receipt or overbilling', text: 'Receipts can’t exceed the PO, and payment is blocked until billed matches received.', where: 'Database rule' },
  { title: 'No payments to suppliers on hold', text: 'Critical risk places a hold that new POs and payments can’t get past.', where: 'Database rule' },
  { title: 'No gaps in PO numbers', text: 'Numbers run per branch and fiscal year, like PO/BLR/2026-27/000123.', where: 'Tested under load' },
  { title: 'No data shared between companies', text: 'Row-level security on every table, keyed to the organization.', where: 'Database rule' },
  { title: 'No AI acting on its own', text: 'The concierge reads with your permissions. It can draft a request; a person submits it.', where: 'By design' },
];

const SEGMENTS = [
  ['Quick commerce and dark stores', 'Hundreds of small, urgent orders for packaging, cold chain and consumables.'],
  ['Restaurant and cloud-kitchen chains', 'Central kitchens supplying outlets in several states, with licensed suppliers.'],
  ['Pharmacy and retail chains', 'Fit-outs, IT and facility services bought locally but paid centrally.'],
  ['Multi-plant manufacturers', 'Indirect spend across plants, each with its own GST registration.'],
];

export default function Home() {
  return (
    <main className="ol">
      <header className="ol-nav">
        <div className="ol-wrap">
          <a href="/" className="brand"><span className="brand-mark" aria-hidden />orrfin<span className="brand-dot">.ai</span></a>
          <nav aria-label="Site">
            <a href="#how" className="hide-sm">How it works</a>
            <a href="#products" className="hide-sm">Products</a>
            <a href="#screens" className="hide-sm">Screens</a>
            <a href="/login">Sign in</a>
            <a href="/demo" className="ol-btn">Open the live demo</a>
          </nav>
        </div>
      </header>

      <section className="ol-hero" aria-labelledby="hero-h">
        <div className="ol-wrap">
          <h1 id="hero-h">Procurement for businesses that buy across many branches</h1>
          <p className="lede">Orrfin.ai takes every purchase from a branch request to a matched invoice in Tally or Zoho Books: approvals, purchase orders, goods receipts and three-way matching in one governed workflow, with Indian GST built in.</p>
          <div className="cta">
            <a href="/demo" className="ol-btn">Open the live demo</a>
            <a href="#how" className="ol-btn ghost">See how it works</a>
          </div>
          <p className="note">No sign-up needed. Pick a role in a fictional company and try it.</p>
        </div>
        <div className="ol-hero-shot ol-wrap">
          <div className="ol-frame">
            <div className="ol-frame-bar"><i /><i /><i /><span>orrfin.ai/app</span></div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/landing/ui/overview.jpg" alt="Orrfin.ai overview: approvals waiting, open orders, invoices to review and monthly spend across ten hubs" width={1600} height={1025} fetchPriority="high" />
          </div>
        </div>
        <div className="ol-hero-band" aria-hidden />
      </section>

      <section id="how" className="ol-section" aria-labelledby="how-h">
        <div className="ol-wrap">
          <Reveal className="ol-head">
            <h2 id="how-h">How a purchase moves through Orrfin.ai</h2>
            <p>Five steps, each done by the right person, with the record of every step kept together.</p>
          </Reveal>
          <ol className="ol-flow">
            {FLOW.map((f, i) => (
              <Reveal as="li" key={f.what} i={i}><b>{f.who}</b><h3>{f.what}</h3><p>{f.text}</p></Reveal>
            ))}
          </ol>
        </div>
      </section>

      <section id="products" className="ol-section alt" aria-labelledby="products-h">
        <div className="ol-wrap">
          <Reveal className="ol-head">
            <h2 id="products-h">Nine products, one purchase record</h2>
            <p>Each product hands its work to the next, so requests, approvals, orders, receipts and bills stay connected.</p>
          </Reveal>
          <div className="ol-products">
            {PRODUCTS.map(({ icon: Icon, name, text }, i) => (
              <Reveal key={name} className="ol-product" i={i % 3}><Icon size={22} aria-hidden /><h3>{name}</h3><p>{text}</p></Reveal>
            ))}
          </div>
        </div>
      </section>

      <section id="screens" className="ol-section" aria-labelledby="screens-h">
        <div className="ol-wrap">
          <Reveal className="ol-head">
            <h2 id="screens-h">See the product</h2>
            <p>Real screens from the demo company. Pick one to see what it does.</p>
          </Reveal>
          <Screens />
        </div>
      </section>

      <section className="ol-section ol-dark" aria-labelledby="rules-h">
        <div className="ol-wrap">
          <Reveal className="ol-head">
            <h2 id="rules-h">Controls that can’t be bypassed</h2>
            <p>The rules that protect money live in the database, so a hurried click, a bulk import or a script can’t get around them.</p>
          </Reveal>
          <ul className="ol-rules">
            {RULES.map((r, i) => <Reveal as="li" key={r.title} i={i % 2}><em>{r.where}</em><strong>{r.title}</strong><p>{r.text}</p></Reveal>)}
          </ul>
        </div>
      </section>

      <section className="ol-section" aria-labelledby="fit-h">
        <div className="ol-wrap ol-fit">
          <Reveal>
            <div className="ol-head" style={{ marginBottom: 24 }}>
              <h2 id="fit-h">Built for multi-branch businesses in India</h2>
              <p>For companies that buy in many places and pay from one finance team.</p>
            </div>
            <dl>{SEGMENTS.map(([t, d]) => <div key={t}><dt>{t}</dt><dd>{d}</dd></div>)}</dl>
          </Reveal>
          <Reveal className="ol-checks" i={1}>
            <h3>A good fit if you have</h3>
            <ul>
              {['10 to 500 stores, kitchens or warehouses', 'More than one GSTIN, or branches in several states', 'A central team approving local spend', 'Zoho Books or Tally Prime as your books', 'Invoices you need to match before paying'].map((t) => <li key={t}><CheckCircle2 size={18} aria-hidden />{t}</li>)}
            </ul>
          </Reveal>
        </div>
      </section>

      <section className="ol-section" style={{ paddingTop: 0 }} aria-labelledby="cta-h">
        <div className="ol-wrap">
          <Reveal className="ol-cta">
            <div>
              <h2 id="cta-h">Try it as anyone in the company</h2>
              <p>Sign in as a store lead, hub manager, procurement, accounts payable, legal, risk or admin, and follow one purchase from request to payment.</p>
            </div>
            <div className="ol-cta-side">
              <a href="/demo" className="ol-btn on-blue">Open the live demo</a>
              <small>Fictional company: 10 hubs, 58 dark stores, a year of history.</small>
            </div>
          </Reveal>
        </div>
      </section>

      <footer className="ol-foot">
        <div className="ol-wrap">
          <span>© {new Date().getFullYear()} Orrfin.ai. The demo company and its suppliers are fictional.</span>
          <nav aria-label="Footer">
            <a href="/demo">Live demo</a>
            <a href="/login">Sign in</a>
            <a href="https://github.com/sumitmishraa/orrfin-AI" rel="noopener noreferrer">GitHub</a>
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
          </nav>
        </div>
      </footer>
    </main>
  );
}
