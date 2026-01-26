import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";
import { Menu, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "NCI Engine - No-Code Intelligence Engine",
  description: "Discover the perfect AI tools for your needs",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background font-sans antialiased">
        <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="container flex h-16 items-center justify-between">
            <div className="flex items-center gap-6">
              <Link href="/" className="flex items-center gap-2 font-semibold">
                <Sparkles className="h-6 w-6 text-emerald-600" />
                <span className="hidden sm:inline-block">NCI Engine</span>
              </Link>
              <nav className="hidden md:flex items-center gap-6 text-sm">
                <Link
                  href="/"
                  className="transition-colors hover:text-emerald-600 text-foreground/60 font-medium"
                >
                  Home
                </Link>
                <Link
                  href="/history"
                  className="transition-colors hover:text-emerald-600 text-foreground/60 font-medium"
                >
                  History
                </Link>
                <Link
                  href="/admin"
                  className="transition-colors hover:text-emerald-600 text-foreground/60 font-medium"
                >
                  Admin
                </Link>
              </nav>
            </div>
            <Button variant="ghost" size="icon" className="md:hidden">
              <Menu className="h-5 w-5" />
            </Button>
          </div>
        </header>
        <main className="flex-1">
          {children}
        </main>
        <Toaster position="top-right" richColors />
        <footer className="border-t py-6 md:py-0">
          <div className="container flex flex-col items-center justify-between gap-4 md:h-16 md:flex-row">
            <p className="text-center text-sm leading-loose text-muted-foreground md:text-left">
              Built with Next.js, FastAPI, and PostgreSQL
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
