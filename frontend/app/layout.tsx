import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
