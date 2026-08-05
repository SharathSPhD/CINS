import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CINS — CST Inverse Newton Solver",
  description:
    "Deterministic monolithic CST-Newton inverse airfoil design — draw a target Cp, get geometry back via a square Newton root-find. No optimizer, no surrogate.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-white text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
        <header className="border-b border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto max-w-5xl px-4 py-3 flex items-center gap-6">
            <Link href="/" className="font-semibold tracking-tight">
              CINS
            </Link>
            <nav className="flex gap-4 text-sm text-neutral-600 dark:text-neutral-400">
              <Link href="/analyze" className="hover:text-neutral-900 dark:hover:text-neutral-100">
                Analyze
              </Link>
              <Link href="/inverse" className="hover:text-neutral-900 dark:hover:text-neutral-100">
                Inverse
              </Link>
              <Link href="/flowfield" className="hover:text-neutral-900 dark:hover:text-neutral-100">
                Flow Field
              </Link>
              <Link href="/gallery" className="hover:text-neutral-900 dark:hover:text-neutral-100">
                Gallery
              </Link>
            </nav>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-neutral-200 dark:border-neutral-800 py-4">
          <div className="mx-auto max-w-5xl px-4 text-xs text-neutral-500">
            CST Inverse Newton Solver — deterministic monolithic inverse airfoil design.
          </div>
        </footer>
      </body>
    </html>
  );
}
