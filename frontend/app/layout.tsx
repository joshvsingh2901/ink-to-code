import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import BackendStatus from "@/components/BackendStatus";
import UploadProvider from "@/components/UploadProvider";
import "./globals.css";

const uiFont = Inter({
  subsets: ["latin"],
  variable: "--font-ui",
  display: "swap",
});

const monoFont = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono-code",
  display: "swap",
});

export const metadata: Metadata = {
  title: "InkToCode",
  description: "Turn handwritten code into editable source files.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${uiFont.variable} ${monoFont.variable}`}>
      <body>
        <UploadProvider>{children}</UploadProvider>
        <BackendStatus />
      </body>
    </html>
  );
}
