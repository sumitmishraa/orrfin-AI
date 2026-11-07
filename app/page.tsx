import Link from 'next/link';
import { ArrowRight, Bot, Boxes, FileSignature, FileText, Inbox, Network, ShieldAlert, Users } from 'lucide-react';

const PRODUCTS = [
  { icon: Inbox, name: 'Intake-to-Procure', text: 'One front door for every branch request. Budgets are checked, preferred suppliers and contracts suggested, and approvals routed by branch, category, amount and risk.' },
  { icon: FileText, name: 'Procure-to-Pay', text: 'Gapless GST-correct purchase orders as PDFs, deliveries recorded at the dark store, supplier invoices read from PDF and matched line by line against the PO and receipt.' },
  { icon: Users, name: 'Supplier Onboarding', text: 'A private portal for suppliers to submit GSTIN, PAN, bank and certificates, with automated checks before anyone can be paid.' },
  { icon: Boxes, name: 'Sourcing', text: 'RFQs through private supplier links. Compare bids by total, lead time, risk and real delivery history, then award to a PO in one click.' },
  { icon: ShieldAlert, name: 'Risk Orchestration', text: 'Explainable risk scores from onboarding, documents and performance. High risk adds an approver; critical risk blocks POs and payments in the database.' },
  { icon: FileSignature, name: 'AI Contract Orchestration', text: 'Generate from your clause library, upload counterparty paper, compare versions, review deviations and never miss a renewal notice.' },
  { icon: Bot, name: 'AI Procurement Concierge', text: 'Ask about spend, orders or suppliers and get answers cited to your own records. It drafts requests; people approve them.' },
  { icon: Network, name: 'ERP push', text: 'Approved POs and bills flow to Zoho Books, or to Tally Prime through a relay that stays on your network. Retried safely, never duplicated.' },
];

export default function Home() {
  return (
    <main className="landing">
      <header className="landing-nav">
        <Link href="/" className="brand light"><span className="brand-mark" aria-hidden>o</span>orrfin<span className="brand-dot">.ai</span></Link>
        <nav aria-label="Site"><a href="#products">Products</a><a href="#how">How it works</a><Link href="/login">Sign in</Link><Link href="/signup" className="button">Start free</Link></nav>
      </header>
      <section className="hero">
        <p className="kicker">Procurement orchestration for multi-branch businesses</p>
        <h1>Every branch.<br /><em>One governed way to buy.</em></h1>
        <p>From a dark-store request in Pune to a matched invoice pushed to your ERP: one workflow with approvals, GST, three-way matching and an audit trail built in.</p>
        <div className="hero-actions"><Link href="/signup" className="button">Create your organization <ArrowRight size={16} aria-hidden /></Link><Link href="/login" className="button ghost">Sign in</Link></div>
      </section>
      <section id="products" className="products">
        {PRODUCTS.map(({ icon: Icon, name, text }) => <article key={name}><Icon aria-hidden /><h2>{name}</h2><p>{text}</p></article>)}
      </section>
      <section id="how" className="how">
        <h2>How a request travels</h2>
        <ol>
          <li><strong>Request.</strong> A store lead asks for 100 insulated bags. The budget is checked and the preferred supplier suggested.</li>
          <li><strong>Approve.</strong> The hub manager, then central procurement, approve. Nobody can approve their own request.</li>
          <li><strong>Order.</strong> A numbered PO is issued under the right GSTIN, as CGST + SGST or IGST, and pushed to the ERP.</li>
          <li><strong>Receive.</strong> The store records 80 of 100 delivered. Over-receipt is impossible.</li>
          <li><strong>Match.</strong> The supplier's PDF invoice is read, a person confirms it, and it's matched against the PO and receipt. Overbilling and price changes are caught.</li>
          <li><strong>Pay.</strong> Once exceptions are resolved, a second person approves and the bill goes to the ERP.</li>
        </ol>
      </section>
      <footer className="landing-foot"><span>© {new Date().getFullYear()} Orrfin.ai</span><span><Link href="/privacy">Privacy</Link> · <Link href="/terms">Terms</Link></span></footer>
    </main>
  );
}
