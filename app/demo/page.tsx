import type { Metadata } from 'next';
import localFont from 'next/font/local';
import '../landing.css';
import RolePicker from '../components/landing/RolePicker';

const switzer = localFont({
  src: [
    { path: '../fonts/switzer-400.woff2', weight: '400' },
    { path: '../fonts/switzer-500.woff2', weight: '500' },
    { path: '../fonts/switzer-600.woff2', weight: '600' },
  ],
  variable: '--font-switzer',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Live demo: Orrfin.ai',
  description: 'Pick a role in the fictional demo company and use Orrfin.ai with that person’s permissions. No sign-up or password.',
};

/** The judges' entry: choose a role, land in the app as that person. No credentials. */
export default function DemoPage() {
  return (
    <main className={`ol ${switzer.variable} ol-demo`}>
      <nav className="ol-nav ol-demo-nav" aria-label="Site">
        <a href="/" className="ol-word">orrfin.ai</a>
        <div className="ol-nav-right"><a href="/">Back to the overview</a><a href="/login">Sign in with an account</a></div>
      </nav>
      <section className="ol-demo-body" aria-labelledby="demo-h">
        <div className="ol-demo-intro">
          <h1 id="demo-h">Pick a role. You&rsquo;re in.</h1>
          <p>Kirnova Quick Commerce is a fictional operator with 10 hubs, 58 dark stores and a year of purchasing history. Each role sees its own screens and can do only what that job allows. Switch roles any time from the menu at the bottom left of the app.</p>
          <p className="ol-demo-tip">To follow one purchase end to end, start as the store lead, then switch to the hub manager, procurement and accounts payable.</p>
        </div>
        <RolePicker />
      </section>
    </main>
  );
}
