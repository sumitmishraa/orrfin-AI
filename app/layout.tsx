import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Orrfin.ai: procurement orchestration for multi-branch businesses',
  description: 'Intake, approvals, sourcing, purchase orders, invoice matching, contracts and supplier risk in one governed workflow, connected to your ERP.',
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en-IN"><body>{children}</body></html>;
}
