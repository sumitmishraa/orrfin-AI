/*
  One "how this works" strip per product screen, keyed by route. Each step is [who, what they do].
  `here` is the step the screen itself is for. Detail pages (/app/orders/123) use their list's guide.
*/
export type GuideSpec = { title?: string; steps: [string, string][]; here?: number };

export const GUIDES: Record<string, GuideSpec> = {
  '/app': {
    title: 'How a purchase moves through Orrfin.ai',
    steps: [
      ['Store lead', 'Raises a request for a branch or site.'],
      ['Managers', 'Approve in order, by amount, category and risk.'],
      ['Procurement', 'Issues the PO, or runs an RFQ first.'],
      ['Store', 'Records what was delivered.'],
      ['Accounts payable', 'Matches the invoice, then a second person approves payment.'],
    ],
  },
  '/app/intake': {
    steps: [
      ['Requester', 'Says what is needed, for which branch, by when.'],
      ['Orrfin.ai', 'Checks budget and prices and suggests preferred suppliers.'],
      ['Approvers', 'Approve in order. Nobody can approve their own request.'],
      ['Procurement', 'Buys from a preferred supplier or runs an RFQ.'],
    ],
    here: 0,
  },
  '/app/approvals': {
    steps: [
      ['Requester', 'Submits a request; the route is built from your approval rules.'],
      ['You', 'Approve, or reject with a reason the requester will see.'],
      ['Next approver', 'Gets the request only after the step before is approved.'],
      ['Procurement', 'Can order once the last step is approved.'],
    ],
    here: 1,
  },
  '/app/sourcing': {
    steps: [
      ['Procurement', 'Invites suppliers to quote on an approved request.'],
      ['Suppliers', 'Bid through a private link, no account needed.'],
      ['Orrfin.ai', 'Ranks bids on total incl. GST, lead time, risk and delivery history.'],
      ['Procurement', 'Awards a bid, which creates the purchase order.'],
    ],
  },
  '/app/orders': {
    steps: [
      ['Procurement', 'Issues the PO: a gapless number and the right GST split.'],
      ['Supplier', 'Gets the PDF, or a private link to view it.'],
      ['Store', 'Records each delivery as a goods receipt.'],
      ['Accounts payable', 'Matches invoices against the PO and the receipts.'],
      ['Automatic', 'Issued POs are sent to your ERP.'],
    ],
  },
  '/app/invoices': {
    steps: [
      ['Accounts payable', 'Uploads the supplier’s PDF or scan.'],
      ['Orrfin.ai', 'Reads the fields and shows how sure it is of each.'],
      ['Accounts payable', 'Confirms the fields and picks the PO.'],
      ['Orrfin.ai', 'Matches each line against the PO and receipts and flags exceptions.'],
      ['A second person', 'Approves payment once blocking exceptions are resolved.'],
    ],
  },
  '/app/erp': {
    steps: [
      ['Admin', 'Connects Zoho Books, or Tally Prime through the relay.'],
      ['Automatic', 'Issued POs and approved bills join the outbox.'],
      ['Automatic', 'Each is delivered once, with retries if the ERP is down.'],
      ['Admin', 'Fixes anything parked for a missing mapping, then retries.'],
    ],
  },
  '/app/suppliers': {
    steps: [
      ['Procurement', 'Adds a supplier or imports a CSV.'],
      ['Procurement', 'Sends the supplier a private onboarding link.'],
      ['Supplier', 'Submits GSTIN, PAN, bank details and certificates.'],
      ['Orrfin.ai', 'Runs format, checksum and expiry checks.'],
      ['Procurement', 'Reviews and approves; only then can the supplier be ordered from.'],
    ],
  },
  '/app/risk': {
    steps: [
      ['Orrfin.ai', 'Scores each supplier from onboarding, documents, deliveries, invoices and spend.'],
      ['Orrfin.ai', 'High risk adds a risk approver to new requests.'],
      ['Orrfin.ai', 'Critical risk places a hold that blocks POs and payments.'],
      ['Risk manager', 'Reviews the evidence and releases or keeps the hold.'],
    ],
  },
  '/app/contracts': {
    steps: [
      ['Procurement or legal', 'Generates a contract from your clause library as Word or PDF.'],
      ['Supplier', 'Sends back their version; you upload it.'],
      ['Orrfin.ai', 'Reviews it clause by clause and compares versions.'],
      ['Legal', 'Approves, then marks it signed.'],
      ['Automatic', 'Renewal and obligation dates become alerts.'],
    ],
  },
  '/app/concierge': {
    steps: [
      ['You', 'Ask a question in plain words.'],
      ['Concierge', 'Looks up only the records your role and branches can see.'],
      ['Concierge', 'Answers with links to the records it used.'],
      ['You', 'Review any drafted request and submit it yourself.'],
    ],
  },
  '/app/admin': {
    steps: [
      ['Admin', 'Adds each GST registration as a legal entity.'],
      ['Admin', 'Adds branches and their sites under the right entity.'],
      ['Admin', 'Invites people with a role and, for local roles, their branches.'],
      ['Admin', 'Sets approval rules by amount, category and branch.'],
    ],
  },
};

export function guideFor(pathname: string | null): { id: string; spec: GuideSpec } | null {
  if (!pathname) return null;
  const base = pathname === '/app' ? '/app' : pathname.split('/').slice(0, 3).join('/');
  const spec = GUIDES[base];
  return spec ? { id: base, spec } : null;
}
