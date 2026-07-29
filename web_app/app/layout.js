import "./styles.css";

export const metadata = {
  title: "CROUS operations",
  description: "Protected administration for CROUS accommodation monitoring",
};

export default function RootLayout({ children }) {
  return <html lang="en" suppressHydrationWarning><body>{children}</body></html>;
}
