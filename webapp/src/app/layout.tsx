import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Seekerthon",
  description: "TikTok-style hackathon voting for Seeker users",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 min-h-screen">
        <Providers>
          <nav className="bg-white border-b border-gray-200 px-6 py-4">
            <div className="max-w-4xl mx-auto flex items-center justify-between">
              <a href="/" className="text-lg font-bold text-purple-600">
                Seekerthon
              </a>
              <div className="flex gap-6 text-sm">
                <a href="/hackathons/create" className="text-gray-600 hover:text-purple-600">
                  Create Hackathon
                </a>
              </div>
            </div>
          </nav>
          <main>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
