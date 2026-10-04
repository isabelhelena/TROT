import './globals.css';

export const metadata = {
  title: 'TROT | Family call oversight',
  description: 'Call updates and alerts for seniors and their trusted guardians.',
};

export default function RootLayout({ children }) {
  return <html lang="en" className="h-full antialiased"><body className="min-h-full flex flex-col">{children}</body></html>;
}
