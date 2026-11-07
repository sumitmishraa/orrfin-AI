'use client';
import { ReactNode, useEffect, useState } from 'react';
import { Brand } from '../components/Shell';

/** Reads the one-time token from the URL fragment, which browsers never send to servers. */
export function usePortalToken() {
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => { setToken(window.location.hash.slice(1) || ''); }, []);
  return token;
}

export function PortalFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="portal">
      <header><Brand /><span>Supplier portal</span></header>
      <h1>{title}</h1>
      {children}
      <footer>This private link is for one record only. Don't forward it. Contact the buyer if you have questions.</footer>
    </main>
  );
}
