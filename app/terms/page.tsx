import Link from 'next/link';

export default function Terms() {
  return (
    <main className="policy-page">
      <Link href="/">← Orrfin.ai</Link>
      <h1>Terms of use</h1>
      <p>Orrfin.ai coordinates purchase requests, approvals, sourcing, purchase orders, goods receipts, invoice matching, contracts and supplier risk. Your organization remains responsible for verifying suppliers, approving purchases and checking every record before acting on it.</p>
      <p>Orrfin.ai does not move money. Payment status is recorded only. Invoice fields read from documents must be confirmed by a person before they are used. Automated contract reviews are not legal advice. GSTIN checks confirm format and checksum only, not registration with GSTN. Sanctions and bank verification are not performed unless a provider is connected.</p>
      <p>ERP connections send approved documents to systems you connect; check the first deliveries in your ERP before relying on them. See the <Link href="/privacy">privacy notice</Link> for how data is handled.</p>
      <p>Updated 7 November 2026.</p>
    </main>
  );
}
