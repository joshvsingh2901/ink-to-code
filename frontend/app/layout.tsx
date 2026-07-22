import type { Metadata } from "next";
import BackendStatus from "@/components/BackendStatus";
import UploadProvider from "@/components/UploadProvider";
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
      <body>
        <UploadProvider>{children}</UploadProvider>
        <BackendStatus />
      </body>
    </html>
  );
}
