import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { Edit, Analysis } from "./types";
import { money, monthName } from "./api";

export function Icon({ name = "wallet" }: { name?: string }) {
  const icons: Record<string, string> = {
    wallet: "wallet",
    overview: "table-cells-large",
    transactions: "right-left",
    budget: "receipt",
    calendar: "calendar-days",
    chart: "chart-column",
    import: "file-import",
    loan: "building-columns"
  };
  return (
    <span
      className={`app-icon image-icon icon-${icons[name] || icons.wallet}`}
      aria-hidden="true"
    />
  );
}
export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Metric({
  label,
  value,
  note,
  positive
}: {
  label: string;
  value: string;
  note?: string;
  positive?: boolean;
}) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong className={positive ? "positive" : ""}>{value}</strong>
      {note && <small>{note}</small>}
    </article>
  );
}
export function FormDialog({
  edit,
  onClose,
  onSave
}: {
  edit: Edit;
  onClose: () => void;
  onSave: (values: Record<string, unknown>) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const values: Record<string, unknown> = {};
    const form = new FormData(e.currentTarget);
    for (const f of edit.fields) {
      let value: unknown = form.get(f.name);
      if (f.type === "checkbox") value = value === "on";
      else if (
        [
          "account_id",
          "source_id",
          "target_id",
          "category_id",
          "transaction_id",
          "debit_id",
          "credit_id",
          "months"
        ].includes(f.name)
      )
        value = value ? Number(value) : null;
      else if (f.type === "month") value = String(value) + "-01";
      values[f.name] = value;
    }
    try {
      await onSave(values);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={ref}
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <form onSubmit={submit}>
        <header className="section-head">
          <h2 id="dialog-title">{edit.title}</h2>
          <button
            type="button"
            className="text-button"
            aria-label="Fermer"
            onClick={onClose}
            disabled={busy}
          >
            ×
          </button>
        </header>
        {edit.fields.map((f) => (
          <label className="field" key={f.name}>
            {f.label}
            {f.options ? (
              <select
                name={f.name}
                required={f.required !== false}
                defaultValue={String(edit.initial?.[f.name] ?? "")}
              >
                {f.required === false && <option value="">Sans catégorie</option>}
                {f.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                name={f.name}
                type={f.type || "text"}
                required={f.type !== "checkbox" && f.required !== false}
                step={f.type === "number" ? "0.01" : undefined}
                min={f.min}
                max={f.max}
                maxLength={250}
                defaultChecked={
                  f.type === "checkbox" ? Boolean(edit.initial?.[f.name] ?? true) : undefined
                }
                defaultValue={
                  f.type === "checkbox" ? undefined : String(edit.initial?.[f.name] ?? "")
                }
              />
            )}
            {f.help && <small>{f.help}</small>}
          </label>
        ))}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            Annuler
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
export function HistoryChart({ rows }: { rows: Analysis["history"] }) {
  const ceiling = Math.max(1, ...rows.flatMap((r) => [r.income, r.spending]));
  return (
    <>
      <div className="legend">
        <span>
          <i className="dot income" />
          Revenus
        </span>
        <span>
          <i className="dot expense" />
          Dépenses
        </span>
      </div>
      <div
        className="history-chart"
        role="img"
        aria-label="Comparaison des revenus et dépenses sur six mois"
      >
        {rows.map((r) => (
          <div className="chart-column" key={r.month}>
            <div className="bar-pair">
              <div
                className="bar income"
                style={{
                  height: Math.max(1, (r.income / ceiling) * 100) + "%"
                }}
                title={"Revenus " + money(r.income)}
              />
              <div
                className="bar expense"
                style={{
                  height: Math.max(1, (r.spending / ceiling) * 100) + "%"
                }}
                title={"Dépenses " + money(r.spending)}
              />
            </div>
            <span>{monthName(r.month, true)}</span>
          </div>
        ))}
      </div>
      <details className="chart-data">
        <summary>Afficher les montants</summary>
        <div className="table-scroll" role="region" aria-label="Montants sur six mois" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th>Mois</th>
                <th>Revenus</th>
                <th>Dépenses</th>
                <th>Solde</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.month}>
                  <td>{monthName(r.month)}</td>
                  <td>{money(r.income)}</td>
                  <td>{money(r.spending)}</td>
                  <td>{money(r.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
export function Footer() {
  return (
    <footer className="site-footer">
      <a className="footer-signature" href="https://portfolio--ninette.ctn.rs/">
        <img
          className="footer-logo"
          src="/images/logo.svg"
          alt=""
          loading="lazy"
          decoding="async"
        />
        <span>L’atelier de ninette</span>
      </a>
      <p className="footer-hosting">Hébergé par Simple Containers</p>
      <div className="social-links">
        <a
          href="https://www.linkedin.com/in/marie-rainaud"
          target="_blank"
          rel="noreferrer"
          aria-label="LinkedIn, nouvel onglet"
        >
          <span className="image-icon icon-linkedin" aria-hidden="true"></span>
          <span>LinkedIn</span>
        </a>
        <a
          href="https://github.com/MarieRainaud"
          target="_blank"
          rel="noreferrer"
          aria-label="GitHub, nouvel onglet"
        >
          <span className="image-icon icon-github" aria-hidden="true"></span>
          <span>GitHub</span>
        </a>
      </div>
    </footer>
  );
}
