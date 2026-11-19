import { renderTransactions } from "./transaction-table";
import { openItemEditor } from "./item-editor";
import { FinancialOverview } from "./FinancialOverview";
import { FinancialAccounts } from "./FinancialAccounts";
import { FinancialTransactions } from "./FinancialTransactions";
import { FinancialBudget } from "./FinancialBudget";
import { FinancialRecurring } from "./FinancialRecurring";
import { FinancialLoans } from "./FinancialLoans";
import { FinancialAnalysis } from "./FinancialAnalysis";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import { api, money, day } from "./api";
import type { Data, Edit, Field, Item, Session } from "./types";
import { Icon, FormDialog, Footer } from "./components";
import { ImportPage } from "./imports";
import "./style.css";
import "./tables.css";

const tabs = [
  ["overview", "Vue d’ensemble"],
  ["wallet", "Comptes"],
  ["transactions", "Opérations"],
  ["budget", "Budget"],
  ["calendar", "Échéances"],
  ["loan", "Prêts"],
  ["chart", "Analyses"],
  ["import", "Imports"]
];
const text = (name: string, label: string, help?: string): Field => ({
  name,
  label,
  help
});
const number = (name: string, label: string, min?: string): Field => ({
  name,
  label,
  type: "number",
  min
});
const dateField = (name: string, label: string): Field => ({
  name,
  label,
  type: "date"
});

function App() {
  const [session, setSession] = useState<Session | null>(null),
    [data, setData] = useState<Data | null>(null);
  const [tab, setTab] = useState("overview"),
    [month, setMonth] = useState(new Date().toLocaleDateString("sv-SE").slice(0, 7)),
    [account, setAccount] = useState(""),
    [category, setCategory] = useState(""),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1);
  const [edit, setEdit] = useState<Edit | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const sequence = useRef(0);
  const query = new URLSearchParams({
    month: month + "-01",
    page: String(page),
    search,
    ...(account ? { account_id: account } : {}),
    ...(category ? { category_id: category } : {})
  });
  async function load() {
    const seq = ++sequence.current;
    setLoading(true);
    try {
      const result = await api<Data>("/state?" + query);
      if (seq === sequence.current) setData(result);
    } catch (e) {
      if (seq === sequence.current) setError((e as Error).message);
    } finally {
      if (seq === sequence.current) setLoading(false);
    }
  }
  async function readSession() {
    let next = await api<Session>("/session");
    if (next.mode === "demo" && !next.authenticated) {
      await api("/demo", { method: "POST" });
      next = await api<Session>("/session");
    }
    return next;
  }
  useEffect(() => {
    readSession()
      .then((s) => {
        setSession(s);
        const reason = new URLSearchParams(window.location.search).get("auth_error");
        if (reason) {
          setError(
            reason === "unavailable"
              ? "Le service de comptes est momentanément indisponible."
              : "La connexion n’a pas abouti. Une nouvelle tentative peut être lancée."
          );
          history.replaceState(null, "", "/");
        }
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    const clear = () => {
      sequence.current++;
      setData(null);
      setEdit(null);
      setSession((previous) => (previous ? { ...previous, authenticated: false } : previous));
      setLoading(false);
    };
    const check = () => {
      if (document.visibilityState !== "visible") return;
      readSession()
        .then((next) => {
          setSession(next);
          if (!next.authenticated) clear();
        })
        .catch(() => {});
    };
    window.addEventListener("finance-session-expired", clear);
    window.addEventListener("focus", check);
    return () => {
      window.removeEventListener("finance-session-expired", clear);
      window.removeEventListener("focus", check);
    };
  }, []);
  useEffect(() => {
    if (session?.authenticated) {
      const timer = setTimeout(load, 180);
      return () => clearTimeout(timer);
    } else if (session) setLoading(false);
  }, [session, month, account, category, search, page]);
  function selectTab(next: string) {
    setTab(next);
    setError("");
    setNotice("");
    if (next === "budget") setAccount("");
  }
  async function act(path: string, body?: unknown, method = "POST") {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api(path, {
        method,
        ...(body ? { body: JSON.stringify(body) } : {})
      });
      await load();
      return result;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(values: Record<string, unknown>) {
    if (!edit) return;
    await api(
      edit.endpoint || "/items/" + edit.resource + (edit.initial?.id ? "/" + edit.initial.id : ""),
      {
        method: edit.method || (edit.initial?.id ? "PUT" : "POST"),
        body: JSON.stringify(values)
      }
    );
    setEdit(null);
    setNotice("Enregistrement effectué");
    await load();
  }
  const today = data?.today || new Date().toLocaleDateString("sv-SE");
  const accountOpts = data?.accounts.map((a) => ({ value: a.id, label: a.name })) || [];
  const categoryOpts = data?.categories.map((c) => ({ value: c.id, label: c.name })) || [];
  const accountField: Field = {
    name: "account_id",
    label: "Compte",
    options: accountOpts
  };
  const catField: Field = {
    name: "category_id",
    label: "Catégorie",
    options: categoryOpts,
    required: false
  };
  function open(resource: string, item?: Item, extra?: Record<string, unknown>) {
    return openItemEditor(
      { text, number, dateField, today, accountField, catField, accountOpts, data, month, setEdit },
      resource,
      item,
      extra
    );
  }
  async function remove(resource: string, item: Item) {
    const warning =
      resource === "transactions" && item.transfer
        ? "Supprimer les deux écritures de ce virement ?"
        : "Supprimer cet élément ?";
    if (window.confirm(warning))
      await act("/items/" + resource + "/" + item.id, undefined, "DELETE");
  }
  function transfer() {
    setEdit({
      resource: "transfers",
      endpoint: "/transfers",
      title: "Virement entre comptes",
      fields: [
        { name: "source_id", label: "Compte débité", options: accountOpts },
        { name: "target_id", label: "Compte crédité", options: accountOpts },
        dateField("date", "Date"),
        number("amount", "Montant", "0.01"),
        text("label", "Libellé")
      ],
      initial: {
        date: today,
        label: "Virement entre comptes",
        source_id: accountOpts[0]?.value,
        target_id: accountOpts[1]?.value
      }
    });
  }
  function repay(loan: Item) {
    setEdit({
      resource: "",
      endpoint: "/loans/" + loan.id + "/repay",
      title: "Enregistrer un remboursement",
      fields: [
        accountField,
        dateField("date", "Date du règlement"),
        number("amount", "Montant remboursé", "0.01")
      ],
      initial: {
        date: today,
        amount: loan.installment,
        account_id: accountOpts[0]?.value
      }
    });
  }
  function matchLoan(loan: Item) {
    const options =
      data?.transactions
        .filter(
          (t) =>
            Number(t.amount) < 0 &&
            !t.transfer &&
            !data.repayments.some((r) => r.transaction_id === t.id)
        )
        .map((t) => ({
          value: t.id,
          label: day(t.date) + " - " + t.label + " - " + money(t.amount)
        })) || [];
    if (!options.length) {
      setError("Aucune dépense disponible parmi les opérations du mois affiché");
      return;
    }
    setEdit({
      resource: "",
      endpoint: "/loans/" + loan.id + "/match",
      title: "Rattacher une opération au prêt",
      fields: [{ name: "transaction_id", label: "Opération du mois affiché", options }],
      initial: { transaction_id: options[0].value }
    });
  }
  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api("/login", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form))
      });
      setSession(await api<Session>("/session"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const catName = (id: number | null) =>
    data?.categories.find((c) => c.id === id)?.name || "À classer";
  const accountName = (id: number) => data?.accounts.find((a) => a.id === id)?.name || "Compte";
  const a = data?.analysis;
  const editButtons = (resource: string, item: Item) => (
    <div className="row-actions">
      <button className="text-button" onClick={() => open(resource, item)}>
        Modifier
      </button>
      <button className="text-button danger" disabled={busy} onClick={() => remove(resource, item)}>
        Supprimer
      </button>
    </div>
  );
  function transactions(compact = false) {
    return renderTransactions(
      { data, today, accountName, catName, busy, act, remove, editButtons },
      compact
    );
  }
  return (
    <div className="app">
      <a className="skip-link" href="#content">
        Aller au contenu
      </a>
      <header className="app-header">
        <div className="mode-line">
          <span className="mode-indicator" />
          {session?.mode === "demo"
            ? "Démonstration - données entièrement fictives"
            : "Espace personnel"}
          {session?.authenticated && (
            <div className="session-actions">
              {session.mode === "demo" ? (
                <div className="actions">
                  {session.private_url && (
                    <a className="text-button" href={session.private_url}>
                      Accéder à l’espace personnel
                    </a>
                  )}
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      if (confirm("Réinitialiser les données fictives de cette session ?"))
                        act("/demo/reset");
                    }}
                  >
                    Réinitialiser la démo
                  </button>
                </div>
              ) : session.auth_mode === "oidc" ? (
                <div className="actions">
                  <a href={session.account_url} className="text-button">
                    Gérer le compte
                  </a>
                  <a href="/auth/logout" className="text-button">
                    Déconnexion
                  </a>
                </div>
              ) : (
                <button
                  className="text-button"
                  onClick={async () => {
                    await api("/logout", { method: "POST" });
                    setData(null);
                    setSession({ ...session, authenticated: false });
                  }}
                >
                  Déconnexion
                </button>
              )}
            </div>
          )}
        </div>
        <h1>
          <Icon />
          Gestionnaire financier
        </h1>
        <p className="introduction">Les comptes, le budget et les échéances au même endroit.</p>
      </header>
      {session?.authenticated && (
        <nav className="main-nav" aria-label="Navigation principale">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => selectTab(key)}
            >
              <Icon name={key} />
              {label}
            </button>
          ))}
        </nav>
      )}
      {session?.authenticated && (
        <label className="mobile-nav">
          Navigation
          <select value={tab} onChange={(e) => selectTab(e.target.value)}>
            {tabs.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
      )}
      <main id="content" aria-busy={loading}>
        {error && (
          <div className="error" role="alert">
            {error}
            <button
              className="text-button"
              onClick={() => setError("")}
              aria-label="Fermer le message"
            >
              ×
            </button>
          </div>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {!session && (
          <p role="status">
            {loading ? "Chargement de l’espace…" : "Connexion au serveur indisponible"}
            {!loading && <button onClick={() => location.reload()}>Réessayer</button>}
          </p>
        )}
        {session && !session.authenticated && session.auth_mode === "oidc" && (
          <section className="login panel account-entry">
            <h2>Connexion</h2>
            <div className="account-entry-actions">
              <a className="button primary" href={session.login_url}>
                Se connecter
              </a>
              <a className="button" href={session.register_url}>
                Créer un compte
              </a>
            </div>
            {session.demo_url && (
              <p className="demo-entry">
                <a href={session.demo_url}>Découvrir la démonstration avec des données fictives</a>
              </p>
            )}
          </section>
        )}
        {session && !session.authenticated && session.auth_mode !== "oidc" && (
          <section className="login panel">
            <h2>Connexion à l’espace privé</h2>
            <form onSubmit={login}>
              <label className="field">
                Adresse e-mail
                <input type="email" name="email" autoComplete="username" required />
              </label>
              <label className="field">
                Mot de passe
                <input type="password" name="password" autoComplete="current-password" required />
              </label>
              <button className="primary" disabled={busy}>
                Se connecter
              </button>
            </form>
          </section>
        )}
        {session?.authenticated && !data && <p role="status">Chargement des comptes…</p>}
        {data && a && (
          <>
            {["overview", "transactions", "budget", "chart"].includes(tab) && (
              <div className="filters">
                <label>
                  Mois
                  <input
                    type="month"
                    value={month}
                    onChange={(e) => {
                      setMonth(e.target.value || today.slice(0, 7));
                      setPage(1);
                    }}
                  />
                </label>
                {tab !== "budget" && (
                  <label>
                    Compte
                    <select
                      value={account}
                      onChange={(e) => {
                        setAccount(e.target.value);
                        setPage(1);
                      }}
                    >
                      <option value="">Tous les comptes</option>
                      {accountOpts.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {loading && (
                  <span className="filters-note" role="status">
                    Actualisation…
                  </span>
                )}
              </div>
            )}
            {tab === "overview" && (
              <FinancialOverview
                open={open}
                a={a}
                today={today}
                selectTab={selectTab}
                data={data}
                account={account}
                accountName={accountName}
                transactions={transactions}
              />
            )}
            {tab === "wallet" && (
              <FinancialAccounts
                transfer={transfer}
                data={data}
                open={open}
                a={a}
                today={today}
                setAccount={setAccount}
                setPage={setPage}
                selectTab={selectTab}
                editButtons={editButtons}
              />
            )}
            {tab === "transactions" && (
              <FinancialTransactions
                transfer={transfer}
                data={data}
                accountName={accountName}
                setError={setError}
                setEdit={setEdit}
                open={open}
                search={search}
                setSearch={setSearch}
                setPage={setPage}
                category={category}
                setCategory={setCategory}
                categoryOpts={categoryOpts}
                transactions={transactions}
                page={page}
                loading={loading}
                editButtons={editButtons}
                catName={catName}
                busy={busy}
                act={act}
                setNotice={setNotice}
              />
            )}
            {tab === "budget" && (
              <FinancialBudget
                open={open}
                data={data}
                a={a}
                catName={catName}
                editButtons={editButtons}
              />
            )}
            {tab === "calendar" && (
              <FinancialRecurring
                open={open}
                data={data}
                a={a}
                accountName={accountName}
                today={today}
                busy={busy}
                act={act}
                setError={setError}
                setEdit={setEdit}
                editButtons={editButtons}
              />
            )}
            {tab === "loan" && (
              <FinancialLoans
                open={open}
                data={data}
                a={a}
                repay={repay}
                matchLoan={matchLoan}
                busy={busy}
                act={act}
                editButtons={editButtons}
              />
            )}
            {tab === "chart" && (
              <FinancialAnalysis
                a={a}
                month={month}
                today={today}
                catName={catName}
                account={account}
              />
            )}
            {tab === "import" && (
              <ImportPage
                mode={session!.mode}
                data={data}
                onImported={async (message) => {
                  setNotice(message);
                  await load();
                }}
              />
            )}
          </>
        )}
      </main>
      <Footer />
      {edit && (
        <FormDialog
          key={JSON.stringify(edit)}
          edit={edit}
          onClose={() => setEdit(null)}
          onSave={async (values) => {
            if (edit.endpoint?.match(/^\/recurring\/\d+\/match$/)) {
              await api(edit.endpoint + "/" + values.transaction_id, {
                method: "POST"
              });
              setEdit(null);
              await load();
            } else await save(values);
          }}
        />
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
