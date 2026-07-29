"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { messages, resolveLocale } from "./messages";

const API = "/crous_bot_api/admin";
const LOCALE_CHOICES = new Set(["fr", "ru"]);
const THEME_CHOICES = new Set(["system", "light", "dark"]);

function browserLocale() {
  return typeof navigator === "undefined" ? "en" : resolveLocale(navigator.language);
}

function csrfToken() {
  return document.cookie.split("; ").find((entry) => entry.startsWith("crous_admin_csrf="))?.split("=")[1] || "";
}

class RequestError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}, retried = false) {
  const method = options.method || "GET";
  const response = await fetch(`${API}${path}`, {
    ...options,
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(method !== "GET" ? { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() } : {}),
      ...(options.headers || {})
    }
  });
  if (response.status === 401 && !retried && path !== "/auth/refresh" && path !== "/auth/login") {
    const refreshed = await fetch(`${API}/auth/refresh`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfToken(), Origin: window.location.origin }
    });
    if (refreshed.ok) return request(path, options, true);
  }
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new RequestError(body?.detail || "Request failed", response.status);
  return body;
}

function useRemote(fetcher, dependencies) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const reload = useCallback(() => {
    const controller = new AbortController();
    setState((current) => ({ ...current, loading: true, error: null }));
    fetcher(controller.signal)
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((error) => {
        if (error.name !== "AbortError") setState({ loading: false, data: null, error });
      });
    return () => controller.abort();
  }, dependencies);
  useEffect(reload, [reload]);
  return { ...state, reload };
}

function formatMoney(value, locale) {
  return new Intl.NumberFormat(locale, { style: "currency", currency: "EUR" }).format((value || 0) / 100);
}

function formatDate(value, locale) {
  return value ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : messages[locale].unknown;
}

function Dialog({ title, onClose, children, t }) {
  const ref = useRef(null);
  const restore = useRef(typeof document !== "undefined" ? document.activeElement : null);
  const titleId = useId();
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const background = document.querySelector(".app-shell");
    document.body.style.overflow = "hidden";
    if (background) {
      background.inert = true;
      background.setAttribute("aria-hidden", "true");
    }
    const focusable = ref.current?.querySelector("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
    focusable?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const elements = [...ref.current.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")];
        if (!elements.length) return;
        const first = elements[0];
        const last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      if (background) {
        background.inert = false;
        background.removeAttribute("aria-hidden");
      }
      document.removeEventListener("keydown", onKeyDown);
      restore.current?.focus?.();
    };
  }, [onClose]);
  return createPortal(<div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId}><header className="modal-header"><h2 id={titleId}>{title}</h2><button className="icon-button" type="button" onClick={onClose} aria-label={t("close")}>×</button></header>{children}</section></div>, document.body);
}

function Preferences({ theme, onThemeChange, localePreference, onLocaleChange, t }) {
  return <div className="preferences"><div className="theme-switcher" role="group" aria-label={t("appearance")}>{[["system", "automatic"], ["light", "light"], ["dark", "dark"]].map(([value, label]) => <button key={value} type="button" className={theme === value ? "selected" : ""} aria-pressed={theme === value} onClick={() => onThemeChange(value)}>{t(label)}</button>)}</div><label className="language-picker"><span className="sr-only">{t("language")}</span><select value={localePreference} onChange={(event) => onLocaleChange(event.target.value)} aria-label={t("language")}><option value="system">{t("automatic")}</option><option value="fr" lang="fr">Français</option><option value="ru" lang="ru">Русский</option></select></label></div>;
}

function Login({ onSignedIn, t, locale, theme, onThemeChange, localePreference, onLocaleChange }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const usernameId = useId();
  const passwordId = useId();
  async function submit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const data = await request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }), headers: { Origin: window.location.origin } });
      onSignedIn(data.admin);
    } catch {
      setError(t("invalidLogin"));
    } finally {
      setSubmitting(false);
    }
  }
  return <main className="login-shell"><section className="login-panel" aria-labelledby="login-title"><div className="brand-mark" aria-hidden="true">C</div><h1 id="login-title">{t("appName")}</h1><p>{t("signInHelp")}</p><form onSubmit={submit} noValidate><label htmlFor={usernameId}>{t("username")}</label><input id={usernameId} name="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required dir="ltr" /><label htmlFor={passwordId}>{t("password")}</label><div className="password-field"><input id={passwordId} name="password" type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-pressed={showPassword}>{showPassword ? t("hidePassword") : t("showPassword")}</button></div><p className="field-help">{t("passwordHelp")}</p>{error && <p className="form-error" role="alert">{error}</p>}<button className="button button-primary" type="submit" disabled={submitting}>{t("signIn")}</button></form><div className="login-preferences"><Preferences theme={theme} onThemeChange={onThemeChange} localePreference={localePreference} onLocaleChange={onLocaleChange} t={t} /></div><p className="locale-line">{new Intl.DisplayNames([locale], { type: "language" }).of(locale)}</p></section></main>;
}

function Status({ loading, error, empty, onRetry, t, children }) {
  if (loading) return <div className="loading-state" aria-live="polite"><span>{t("loading")}</span><i /><i /><i /></div>;
  if (error) return <div className="error-state" role="alert"><span>{t("error")}</span><button type="button" className="text-button" onClick={onRetry}>{t("retry")}</button></div>;
  if (empty) return <div className="empty-state">{t("empty")}</div>;
  return children;
}

function Pagination({ meta, onPage, t }) {
  if (!meta) return null;
  const pages = Array.from({ length: Math.min(meta.pages, 7) }, (_, index) => index + 1);
  return <nav className="pagination" aria-label={t("page")}><button type="button" onClick={() => onPage(meta.page - 1)} disabled={meta.page === 1}>{t("previous")}</button>{pages.map((number) => <button key={number} type="button" className={number === meta.page ? "active" : ""} onClick={() => onPage(number)} aria-current={number === meta.page ? "page" : undefined}>{number}</button>)}<button type="button" onClick={() => onPage(meta.page + 1)} disabled={meta.page >= meta.pages}>{t("next")}</button><span aria-live="polite">{t("page")} {meta.page} {t("of")} {meta.pages} · {meta.total} {t("results")}</span></nav>;
}

function RevenueChart({ series, locale, t }) {
  const [selected, setSelected] = useState(series?.length ? series.length - 1 : 0);
  useEffect(() => setSelected(series?.length ? series.length - 1 : 0), [series]);
  if (!series?.length) return <div className="empty-state">{t("noData")}</div>;
  const max = Math.max(...series.map((point) => point.amount_cents), 1);
  const selectedPoint = series[selected] || series[0];
  const points = series.map((point, index) => `${index * (100 / Math.max(series.length - 1, 1))},${100 - (point.amount_cents / max) * 86}`).join(" ");
  return <div className="chart" aria-label={t("revenue")}><div className="chart-tooltip" aria-live="polite"><span>{selectedPoint.key}</span><strong>{formatMoney(selectedPoint.amount_cents, locale)}</strong></div><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${t("revenue")}: ${formatMoney(selectedPoint.amount_cents, locale)}`}><polygon className="chart-fill" points={`0,100 ${points} 100,100`} /><polyline className="chart-line" points={points} /></svg><div className="chart-points">{series.map((point, index) => <button key={point.key} type="button" className={index === selected ? "selected" : ""} style={{ left: `${index * (100 / Math.max(series.length - 1, 1))}%`, bottom: `${(point.amount_cents / max) * 86}%` }} onMouseEnter={() => setSelected(index)} onFocus={() => setSelected(index)} onClick={() => setSelected(index)} aria-label={`${point.key}: ${formatMoney(point.amount_cents, locale)}`} />)}</div></div>;
}

function Dashboard({ locale, t }) {
  const [period, setPeriod] = useState("month");
  const dashboard = useRemote((signal) => request(`/dashboard?period=${period}`, { signal }), [period]);
  const buyers = useRemote((signal) => request("/dashboard/recent-buyers", { signal }), []);
  const data = dashboard.data;
  return <section className="view"><header className="view-header"><div><h1>{t("dashboard")}</h1><p>{t("overview")}</p></div><div className="segmented" aria-label={t("filters")}>{["week", "month", "year"].map((key) => <button key={key} type="button" className={period === key ? "selected" : ""} onClick={() => setPeriod(key)}>{t(key)}</button>)}</div></header><Status {...dashboard} empty={false} t={t}>{data && <><div className="metrics"><article><span>{t("totalUsers")}</span><strong>{new Intl.NumberFormat(locale).format(data.total_users)}</strong></article><article><span>{t("paidSubscribers")}</span><strong>{new Intl.NumberFormat(locale).format(data.active_paid_subscribers)}</strong></article><article><span>{t("monitoringAnchors")}</span><strong>{new Intl.NumberFormat(locale).format(data.active_monitoring_anchors)}</strong></article></div><section className="revenue-panel"><header><div><h2>{t("revenue")}</h2><strong>{formatMoney(data.revenue_cents, locale)}</strong></div><button className="text-button" type="button" onClick={dashboard.reload}>{t("refresh")}</button></header><RevenueChart series={data.revenue_series} locale={locale} t={t} /></section></>}</Status><section className="data-section"><header><h2>{t("recentBuyers")}</h2></header><Status {...buyers} empty={!buyers.data?.items?.length} t={t}><div className="table-scroll"><table><thead><tr><th>{t("username")}</th><th>{t("plan")}</th><th>{t("amount")}</th><th>{t("purchased")}</th><th>{t("status")}</th></tr></thead><tbody>{buyers.data?.items.map((buyer) => <tr key={buyer.purchase_id}><td>{buyer.username || t("unknown")}</td><td>{buyer.plan}</td><td>{formatMoney(buyer.amount_cents, locale)}</td><td>{formatDate(buyer.purchased_at, locale)}</td><td><span className="status">{buyer.status}</span></td></tr>)}</tbody></table></div></Status></section></section>;
}

function SearchField({ value, onChange, t }) {
  const id = useId();
  return <div className="search-field"><label htmlFor={id}>{t("search")}</label><input id={id} value={value} onChange={(event) => onChange(event.target.value)} /></div>;
}

function AdminForm({ onClose, onCreated, t }) {
  const [form, setForm] = useState({ name: "", username: "", password: "", role: "admin" });
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const ids = { name: useId(), username: useId(), password: useId(), role: useId() };
  const update = (name) => (event) => setForm((current) => ({ ...current, [name]: event.target.value }));
  async function submit(event) {
    event.preventDefault();
    setSubmitting(true); setError("");
    try {
      await request("/admins", { method: "POST", body: JSON.stringify(form), headers: { Origin: window.location.origin } });
      onCreated(); onClose();
    } catch (requestError) {
      setError(requestError.message || t("error"));
    } finally { setSubmitting(false); }
  }
  return <Dialog title={t("createAdmin")} onClose={onClose} t={t}><form className="dialog-form" onSubmit={submit}><label htmlFor={ids.name}>{t("name")}</label><input id={ids.name} value={form.name} onChange={update("name")} required /><label htmlFor={ids.username}>{t("username")}</label><input id={ids.username} value={form.username} onChange={update("username")} required dir="ltr" /><label htmlFor={ids.password}>{t("password")}</label><div className="password-field"><input id={ids.password} type={showPassword ? "text" : "password"} value={form.password} onChange={update("password")} required /><button type="button" onClick={() => setShowPassword((value) => !value)}>{showPassword ? t("hidePassword") : t("showPassword")}</button></div><p className="field-help">{t("passwordHelp")}</p><label htmlFor={ids.role}>{t("role")}</label><select id={ids.role} value={form.role} onChange={update("role")}><option value="admin">{t("admin")}</option><option value="superadmin">{t("superadmin")}</option></select>{error && <p className="form-error" role="alert">{error}</p>}<footer><button className="button" type="button" onClick={onClose}>{t("cancel")}</button><button className="button button-primary" type="submit" disabled={submitting}>{t("save")}</button></footer></form></Dialog>;
}

function Admins({ t, locale, profile }) {
  const [query, setQuery] = useState(""); const [page, setPage] = useState(1); const [adding, setAdding] = useState(false);
  useEffect(() => { const id = setTimeout(() => setPage(1), 250); return () => clearTimeout(id); }, [query]);
  const remote = useRemote((signal) => request(`/admins?q=${encodeURIComponent(query)}&page=${page}`, { signal }), [query, page]);
  return <section className="view"><header className="view-header"><div><h1>{t("administrators")}</h1><p>{remote.data?.meta?.total ?? 0} {t("results")}</p></div>{profile.role === "superadmin" && <button className="button button-primary" type="button" onClick={() => setAdding(true)}>{t("addAdmin")}</button>}</header><SearchField value={query} onChange={setQuery} t={t} /><Status {...remote} empty={!remote.data?.items?.length} t={t}><div className="table-scroll"><table><thead><tr><th>{t("name")}</th><th>{t("username")}</th><th>{t("role")}</th><th>{t("status")}</th><th>{t("created")}</th><th>{t("lastLogin")}</th></tr></thead><tbody>{remote.data?.items.map((item) => <tr key={item.id}><td>{item.name}</td><td dir="ltr">{item.username}</td><td>{t(item.role)}</td><td><span className="status">{item.is_active ? t("active") : t("inactive")}</span></td><td>{formatDate(item.created_at, locale)}</td><td>{formatDate(item.last_login_at, locale)}</td></tr>)}</tbody></table></div><Pagination meta={remote.data?.meta} onPage={setPage} t={t} /></Status>{adding && <AdminForm onClose={() => setAdding(false)} onCreated={remote.reload} t={t} />}</section>;
}

function Details({ type, id, onClose, locale, t }) {
  const endpoint = type === "user" ? `/paid-users/${id}` : `/transactions/${id}`;
  const remote = useRemote((signal) => request(endpoint, { signal }), [endpoint]);
  const item = remote.data;
  return <Dialog title={type === "user" ? t("paidUsers") : t("transaction")} onClose={onClose} t={t}><Status {...remote} empty={false} t={t}>{item && <dl className="details"><div><dt>{t("username")}</dt><dd>{item.username || t("unknown")}</dd></div><div><dt>{t("plan")}</dt><dd>{item.current_plan || item.plan}</dd></div><div><dt>{t("amount")}</dt><dd>{item.amount_cents === undefined ? t("unknown") : formatMoney(item.amount_cents, locale)}</dd></div><div><dt>{t("status")}</dt><dd>{item.status}</dd></div>{type === "user" ? <><div><dt>{t("language")}</dt><dd>{item.language}</dd></div><div><dt>{t("activeSearches")}</dt><dd>{item.active_monitoring_count}</dd></div><div className="details-wide"><dt>{t("searchArea")}</dt><dd><ul>{item.searches.map((search) => <li key={search.id}>{search.location} · {search.is_active ? t("active") : t("inactive")}</li>)}</ul></dd></div></> : <><div><dt>{t("mode")}</dt><dd>{item.is_test ? t("test") : t("live")}</dd></div><div className="details-wide"><dt>{t("identifier")}</dt><dd dir="ltr">{item.stripe_checkout_session_id}</dd></div></>}</dl>}</Status></Dialog>;
}

function PaidUsers({ t, locale }) {
  const [query, setQuery] = useState(""); const [page, setPage] = useState(1); const [selected, setSelected] = useState(null);
  useEffect(() => { const id = setTimeout(() => setPage(1), 250); return () => clearTimeout(id); }, [query]);
  const remote = useRemote((signal) => request(`/paid-users?q=${encodeURIComponent(query)}&page=${page}`, { signal }), [query, page]);
  return <section className="view"><header className="view-header"><div><h1>{t("paidUsers")}</h1><p>{remote.data?.meta?.total ?? 0} {t("results")}</p></div></header><SearchField value={query} onChange={setQuery} t={t} /><Status {...remote} empty={!remote.data?.items?.length} t={t}><div className="table-scroll"><table><thead><tr><th>{t("username")}</th><th>{t("plan")}</th><th>{t("starts")}</th><th>{t("ends")}</th><th>{t("activeSearches")}</th><th><span className="sr-only">{t("viewDetails")}</span></th></tr></thead><tbody>{remote.data?.items.map((item) => <tr key={item.user_id}><td>{item.username || t("unknown")}</td><td>{item.current_plan}</td><td>{formatDate(item.starts_at, locale)}</td><td>{formatDate(item.ends_at, locale)}</td><td>{item.active_monitoring_count}</td><td><button type="button" className="row-action" onClick={() => setSelected(item.user_id)}>{t("viewDetails")}</button></td></tr>)}</tbody></table></div><Pagination meta={remote.data?.meta} onPage={setPage} t={t} /></Status>{selected && <Details type="user" id={selected} onClose={() => setSelected(null)} locale={locale} t={t} />}</section>;
}

function Transactions({ t, locale }) {
  const [query, setQuery] = useState(""); const [page, setPage] = useState(1); const [selected, setSelected] = useState(null);
  useEffect(() => { const id = setTimeout(() => setPage(1), 250); return () => clearTimeout(id); }, [query]);
  const remote = useRemote((signal) => request(`/transactions?q=${encodeURIComponent(query)}&page=${page}`, { signal }), [query, page]);
  return <section className="view"><header className="view-header"><div><h1>{t("transactions")}</h1><p>{remote.data?.meta?.total ?? 0} {t("results")}</p></div></header><SearchField value={query} onChange={setQuery} t={t} /><Status {...remote} empty={!remote.data?.items?.length} t={t}><div className="table-scroll"><table><thead><tr><th>{t("identifier")}</th><th>{t("username")}</th><th>{t("plan")}</th><th>{t("amount")}</th><th>{t("mode")}</th><th>{t("purchased")}</th><th><span className="sr-only">{t("viewDetails")}</span></th></tr></thead><tbody>{remote.data?.items.map((item) => <tr key={item.id}><td>{item.id}</td><td>{item.username || t("unknown")}</td><td>{item.plan}</td><td>{formatMoney(item.amount_cents, locale)}</td><td><span className="status">{item.is_test ? t("test") : t("live")}</span></td><td>{formatDate(item.purchased_at, locale)}</td><td><button type="button" className="row-action" onClick={() => setSelected(item.id)}>{t("viewDetails")}</button></td></tr>)}</tbody></table></div><Pagination meta={remote.data?.meta} onPage={setPage} t={t} /></Status>{selected && <Details type="transaction" id={selected} onClose={() => setSelected(null)} locale={locale} t={t} />}</section>;
}

function Application({ profile, onSignedOut, locale, theme, onThemeChange, localePreference, onLocaleChange, t }) {
  const [view, setView] = useState("dashboard"); const [menuOpen, setMenuOpen] = useState(false); const [help, setHelp] = useState(false);
  const navigation = [["dashboard", "dashboard"], ["administrators", "administrators"], ["paid-users", "paidUsers"], ["transactions", "transactions"]];
  async function signOut() {
    try { await request("/auth/logout", { method: "POST", headers: { Origin: window.location.origin } }); } finally { onSignedOut(); }
  }
  return <div className="app-shell"><a className="skip-link" href="#main-content">{t("skip")}</a><header className="topbar"><button className="brand" type="button" onClick={() => setView("dashboard")}>{t("appName")}</button><div className="topbar-actions"><div className="topbar-preferences"><Preferences theme={theme} onThemeChange={onThemeChange} localePreference={localePreference} onLocaleChange={onLocaleChange} t={t} /></div><button className="button" type="button" onClick={() => setHelp(true)}>{t("keyboardHelp")}</button><button className="button" type="button" onClick={signOut}>{t("signOut")}</button><button className="menu-button" type="button" onClick={() => setMenuOpen((open) => !open)} aria-expanded={menuOpen}>{t("menu")}</button></div></header><aside className={menuOpen ? "sidebar open" : "sidebar"}><p>{t("signedInAs")}</p><strong dir="ltr">{profile.username}</strong><nav aria-label={t("menu")}>{navigation.map(([key, label]) => <button key={key} type="button" onClick={() => { setView(key); setMenuOpen(false); }} aria-current={view === key ? "page" : undefined}>{t(label)}</button>)}</nav><div className="sidebar-tools"><div className="sidebar-preferences"><Preferences theme={theme} onThemeChange={onThemeChange} localePreference={localePreference} onLocaleChange={onLocaleChange} t={t} /></div><button className="button" type="button" onClick={() => setHelp(true)}>{t("keyboardHelp")}</button><button className="button" type="button" onClick={signOut}>{t("signOut")}</button></div></aside><main id="main-content" className="content">{view === "dashboard" && <Dashboard locale={locale} t={t} />}{view === "administrators" && <Admins locale={locale} t={t} profile={profile} />}{view === "paid-users" && <PaidUsers locale={locale} t={t} />}{view === "transactions" && <Transactions locale={locale} t={t} />}</main>{help && <Dialog title={t("keyboardHelp")} onClose={() => setHelp(false)} t={t}><p className="dialog-copy">{t("keyboardBody")}</p><footer className="dialog-footer"><button className="button button-primary" type="button" onClick={() => setHelp(false)}>{t("close")}</button></footer></Dialog>}</div>;
}

export default function Home() {
  const [locale, setLocale] = useState("en"); const [localePreference, setLocalePreference] = useState("system"); const [theme, setTheme] = useState("system"); const [preferencesReady, setPreferencesReady] = useState(false); const [profile, setProfile] = useState(undefined);
  const t = useCallback((key) => messages[locale]?.[key] || messages.en[key] || key, [locale]);
  const chooseLocale = useCallback((value) => { const next = LOCALE_CHOICES.has(value) ? value : "system"; setLocalePreference(next); setLocale(next === "system" ? browserLocale() : next); }, []);
  useEffect(() => { const savedTheme = window.localStorage.getItem("crous-admin-theme"); const savedLocale = window.localStorage.getItem("crous-admin-locale"); const nextTheme = THEME_CHOICES.has(savedTheme) ? savedTheme : "system"; const nextLocale = LOCALE_CHOICES.has(savedLocale) ? savedLocale : "system"; setTheme(nextTheme); setLocalePreference(nextLocale); setLocale(nextLocale === "system" ? browserLocale() : nextLocale); setPreferencesReady(true); }, []);
  useEffect(() => { if (!preferencesReady) return; if (theme === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = theme; window.localStorage.setItem("crous-admin-theme", theme); }, [theme, preferencesReady]);
  useEffect(() => { document.documentElement.lang = locale; document.documentElement.dir = locale === "ar" || locale === "fa" ? "rtl" : "ltr"; if (preferencesReady) window.localStorage.setItem("crous-admin-locale", localePreference); }, [locale, localePreference, preferencesReady]);
  useEffect(() => { request("/me").then(setProfile).catch((error) => setProfile(error.status === 401 ? null : null)); }, []);
  if (profile === undefined) return <main className="boot"><span>{t("loading")}</span></main>;
  return profile ? <Application profile={profile} onSignedOut={() => setProfile(null)} locale={locale} theme={theme} onThemeChange={setTheme} localePreference={localePreference} onLocaleChange={chooseLocale} t={t} /> : <Login onSignedIn={setProfile} t={t} locale={locale} theme={theme} onThemeChange={setTheme} localePreference={localePreference} onLocaleChange={chooseLocale} />;
}
