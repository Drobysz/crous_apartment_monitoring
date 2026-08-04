"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

const API = "/crous_bot_api/referral";
const TOKEN_KEY = "crous_referral_owner_session";

function money(value) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR" }).format(
    (value || 0) / 100,
  );
}

async function ownerRequest(path, token, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.detail?.code || "Unable to load your referral account.");
  return payload;
}

function ReferralDashboard() {
  const params = useSearchParams();
  const [accessToken, setAccessToken] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let live = true;
    async function authenticate() {
      try {
        const loginToken = params.get("token");
        let token = window.sessionStorage.getItem(TOKEN_KEY);
        if (loginToken) {
          const response = await fetch(`${API}/auth/exchange`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ token: loginToken }),
          });
          const payload = await response.json().catch(() => null);
          if (!response.ok) throw new Error(payload?.detail?.code || "This login link has expired.");
          token = payload.access_token;
          window.sessionStorage.setItem(TOKEN_KEY, token);
          window.history.replaceState({}, "", "/referral/dashboard");
        }
        if (!token) throw new Error("Open a new secure link from the referral bot.");
        if (live) setAccessToken(token);
      } catch (value) {
        if (live) setError(value.message);
      }
    }
    authenticate();
    return () => { live = false; };
  }, [params]);

  async function refresh(token = accessToken) {
    if (!token) return;
    try {
      const [owner, history] = await Promise.all([
        ownerRequest("/dashboard", token),
        ownerRequest("/payouts", token),
      ]);
      setDashboard(owner);
      setPayouts(history.items || []);
    } catch (value) {
      window.sessionStorage.removeItem(TOKEN_KEY);
      setError(value.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, [accessToken]);

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
      await ownerRequest("/payouts/request", accessToken, {
        method: "POST",
        body: JSON.stringify({
          amount_cents: amountCents,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      setAmount("");
      await refresh();
    } catch (value) {
      setError(value.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <main className="boot">Loading your referral dashboard…</main>;
  if (error && !dashboard) return <main className="boot"><div className="login-panel"><h1>Referral dashboard</h1><p role="alert">{error}</p></div></main>;
  return <main className="content"><section className="view"><header className="view-header"><div><h1>Referral dashboard</h1><p>Your referral code: <strong>{dashboard.referral_code}</strong></p></div></header><div className="metrics"><article><span>Lifetime commission earned</span><strong>{money(dashboard.earned_cents)}</strong></article><article><span>Available balance</span><strong>{money(dashboard.available_cents)}</strong></article><article><span>Reserved for withdrawal</span><strong>{money(dashboard.reserved_cents)}</strong></article><article><span>Total paid</span><strong>{money(dashboard.paid_cents)}</strong></article></div><section className="data-section"><header><h2>Request a withdrawal</h2></header><form className="dialog-form" onSubmit={requestWithdrawal}><label htmlFor="withdrawal-amount">Available: {money(dashboard.available_cents)}</label><input id="withdrawal-amount" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="5.00" disabled={submitting || dashboard.available_cents < 500} /><button className="button button-primary" type="submit" disabled={submitting || dashboard.available_cents < 500}>{submitting ? "Requesting…" : "Request withdrawal"}</button>{error && <p className="form-error" role="alert">{error}</p>}</form></section><section className="data-section"><header><h2>Withdrawal history</h2></header><div className="table-scroll"><table><thead><tr><th>Requested</th><th>Amount</th><th>Status</th><th>Paid</th></tr></thead><tbody>{payouts.map((payout) => <tr key={payout.id}><td>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(payout.requested_at))}</td><td>{money(payout.amount_cents)}</td><td>{payout.status}</td><td>{payout.paid_at ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(payout.paid_at)) : "—"}</td></tr>)}</tbody></table></div></section></section></main>;
}

export default function ReferralDashboardPage() {
  return <Suspense fallback={<main className="boot">Loading your referral dashboard…</main>}><ReferralDashboard /></Suspense>;
}
