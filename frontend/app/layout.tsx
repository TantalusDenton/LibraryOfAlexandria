import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Library of Alexandria — Turn stories into worlds",
  description:
    "An independent publishing studio for illustrated novels and graphic novels.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
