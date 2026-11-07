import type { Metadata } from 'next';
import '../landing.css';
import RolePicker from '../components/landing/RolePicker';

export const metadata: Metadata = {
  title: 'Live demo: Orrfin.ai',
  description: 'Pick a role in the fictional demo company and use Orrfin.ai with that person’s permissions. No sign-up or password.',
};

/** The judges' entry: choose a role, land in the app as that person. No credentials. */
export default function DemoPage() {
  return (
    <main className="ol" style={{ minHeight: '100vh' }}>
      <header className="ol-nav">
        <div className="ol-wrap">
          <a href="/" className="brand"><span className="brand-mark" aria-hidden />orrfin<span className="brand-dot">.ai</span></a>
          <nav aria-label="Site"><a href="/" className="hide-sm">Back to the overview</a><a href="/login">Sign in with an account</a></nav>
        </div>
      </header>
      <section className="ol-wrap ol-demo-body" aria-labelledby="demo-h">
        <div className="ol-demo-intro">
          <h1 id="demo-h">Pick a role to open the demo</h1>
          <p>Kirnova Quick Commerce is a fictional operator with 10 hubs, 58 dark stores and a year of purchasing history. Each role sees its own screens and can do only what that job allows. No password is needed.</p>
          <p className="ol-demo-tip">To follow one purchase end to end, start as the store lead, then switch to the hub manager, procurement and accounts payable from the menu at the bottom left of the app.</p>
        </div>
        <RolePicker />
      </section>
    </main>
  );
}
