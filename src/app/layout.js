import { DM_Sans } from "next/font/google";
import { FeedbackProvider } from "@/components/Feedback";
import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm",
});

export const metadata = {
  title: "Infralens",
  description: "Multi-client Azure estate console. Each organization connects its own app registration.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${dmSans.variable} h-full antialiased`}>
      <body className="min-h-full bg-canvas font-sans text-ink">
        <FeedbackProvider>{children}</FeedbackProvider>
      </body>
    </html>
  );
}
