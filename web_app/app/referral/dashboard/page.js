"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { messages, resolveLocale } from "../../messages";
import { ReferralDetails } from "../../page";

const API = "/crous_bot_api/referral-owner";

async function ownerRequest(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.detail?.code || "invalid_or_expired_referral_login_token");
  return payload;
}

function money(value, locale) {
  return new Intl.NumberFormat(locale, { style: "currency", currency: "EUR" }).format(
    (value || 0) / 100,
  );
}

function OwnerPayouts({ locale }) {
  const [dashboard, setDashboard] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    const [stats, history] = await Promise.all([ownerRequest("/stats"), ownerRequest("/payouts")]);
    setDashboard(stats);
    setPayouts(history.items || []);
  }, []);

  useEffect(() => { refresh().catch((value) => setError(value.message)); }, [refresh]);

  async function requestWithdrawal(event) {
    event.preventDefault();
    if (!/^\d+(?:\.\d{1,2})?$/.test(amount)) {
      setError("Enter an amount in euros with no more than two decimal places.");
      return;
    }
    const amountCents = Math.round(Number(amount) * 100);
    if (!Number.isFinite(amountCents) || amountCents < 500) {
      setError("The minimum withdrawal is €5.00.");
      return;
    }
    setSubmitting(true); setError("");
    try {
      await ownerRequest("/payouts/request", {
        method: "POST",
        body: JSON.stringify({ amount_cents: amountCents, idempotency_key: crypto.randomUUID() }),
      });
      setAmount("");
      await refresh();
    } catch (value) {
      setError(value.message);
    } finally {
      setSubmitting(false);
    }
  }

  return <section className="view"><section className="data-section"><header><h2>Request a withdrawal</h2></header><form className="dialog-form" onSubmit={requestWithdrawal}><label htmlFor="withdrawal-amount">Available: {money(dashboard?.available_cents, locale)}</label><input id="withdrawal-amount" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="5.00" disabled={submitting || (dashboard?.available_cents || 0) < 500} /><button className="button button-primary" type="submit" disabled={submitting || (dashboard?.available_cents || 0) < 500}>{submitting ? "Requesting…" : "Request withdrawal"}</button>{error && <p className="form-error" role="alert">{error}</p>}</form></section><section className="data-section"><header><h2>Withdrawal history</h2></header><div className="table-scroll"><table><thead><tr><th>Requested</th><th>Amount</th><th>Status</th><th>Paid</th></tr></thead><tbody>{payouts.map((payout) => <tr key={payout.id}><td>{new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(payout.requested_at))}</td><td>{money(payout.amount_cents, locale)}</td><td>{payout.status}</td><td>{payout.paid_at ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(payout.paid_at)) : "—"}</td></tr>)}</tbody></table></div></section></section>;
}

function ReferralDashboard() {
  const params = useSearchParams();
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const locale = resolveLocale(typeof navigator === "undefined" ? "en" : navigator.language);
  const t = useCallback((key) => messages[locale]?.[key] || messages.en[key] || key, [locale]);
  const loadDetail = useCallback((signal) => ownerRequest("/me", { signal }), []);
  const loadStats = useCallback((period, signal) => ownerRequest(`/stats?period=${period}`, { signal }), []);
  const loadPurchases = useCallback((page, signal) => ownerRequest(`/purchases?page=${page}`, { signal }), []);

  useEffect(() => {
    let live = true;
    async function authenticate() {
      try {
        const loginToken = params.get("token");
        if (loginToken) {
          await ownerRequest("/auth/exchange", { method: "POST", body: JSON.stringify({ token: loginToken }) });
          window.history.replaceState({}, "", "/referral/dashboard");
        }
        await ownerRequest("/me");
        if (live) setReady(true);
      } catch (value) {
        if (live) setError(value.message);
      }
    }
    authenticate();
    return () => { live = false; };
  }, [params]);

  if (!ready && !error) return <main className="boot">Loading your referral dashboard…</main>;
  if (error) return <main className="boot"><div className="login-panel"><h1>{t("referralDashboard")}</h1><p role="alert">{t("referralLinkExpired")}</p></div></main>;
  return <main className="content"><ReferralDetails id={0} locale={locale} t={t} onBack={() => {}} loadDetail={loadDetail} loadStats={loadStats} loadPurchases={loadPurchases} /><OwnerPayouts locale={locale} /></main>;
}

export default function ReferralDashboardPage() {
  return <Suspense fallback={<main className="boot">Loading your referral dashboard…</main>}><ReferralDashboard /></Suspense>;
}
