import './globals.css';
import './pilot.css';
import type { Metadata } from 'next';
export const metadata: Metadata = {title:'VendorMind — Better decisions, remembered',description:'Procurement decisions backed by supplier experience.'};
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>}
