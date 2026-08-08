import "./globals.css";

export const metadata = {
  title: "Scout — TIET College Assistant",
  description:
    "AI-powered assistant for Thapar Institute of Engineering & Technology. Get instant answers about admissions, fees, hostel, scholarships, and more.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
