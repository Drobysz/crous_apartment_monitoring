import "./styles.css";

export const metadata = {
  title: "CROUS Bot",
  description: "CROUS accommodation monitoring",
};

export default function RootLayout({ children }) {
  return <html lang="en"><body>{children}</body></html>;
}
