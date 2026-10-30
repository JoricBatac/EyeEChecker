import type { Metadata } from "next";
import { Geist } from "next/font/google";

import { AuthProvider } from "@/lib/auth";

import "./globals.css";

const sans = Geist({ variable: "--font-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ScanAssist",
  description: "Clinic dashboard and internal console",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={sans.variable}>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
