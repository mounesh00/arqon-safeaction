import './globals.css';
export const metadata = { title: 'Arqon OS · Workspace', description: 'Local AI agent workspace' };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
