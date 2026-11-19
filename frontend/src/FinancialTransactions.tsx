import { money } from "./api";
import type { Data, Edit, Item } from "./types";

import type * as React from "react";

import type { Dispatch } from "react";
import type { SetStateAction } from "react";

type FinancialTransactionsProps = {
  transfer: () => void;
  data: Data;
  accountName: (id: number) => string;
  setError: React.Dispatch<React.SetStateAction<string>>;
  setEdit: React.Dispatch<React.SetStateAction<Edit | null>>;
  open: (
    resource: string,
    item?: Item | undefined,
    extra?: Record<string, unknown> | undefined
  ) => void;
  search: string;
  setSearch: React.Dispatch<React.SetStateAction<string>>;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  category: string;
  setCategory: React.Dispatch<React.SetStateAction<string>>;
  categoryOpts: {
    value: number;
    label: string;
  }[];
  transactions: (compact?: boolean) => React.JSX.Element;
  page: number;
  loading: boolean;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
  catName: (id: number | null) => string;
  busy: boolean;
  act: (
    path: string,
    body?: unknown,
    method?: string
  ) => Promise<Record<string, unknown> | undefined>;
  setNotice: React.Dispatch<React.SetStateAction<string>>;
};

export function FinancialTransactions({
  transfer,
  data,
  accountName,
  setError,
  setEdit,
  open,
  search,
  setSearch,
  setPage,
  category,
  setCategory,
  categoryOpts,
  transactions,
  page,
  loading,
  editButtons,
  catName,
  busy,
  act,
  setNotice
}: FinancialTransactionsProps) {
  return (
    <>
      <div className="section-head">
        <h2>Les opérations</h2>
        <div className="actions">
          <button onClick={transfer} disabled={data.accounts.length < 2}>
            Virement
          </button>
          <button
            onClick={() => {
              const eligible = data.transactions.filter(
                (t) =>
                  !t.transfer &&
                  !t.recurring_id &&
                  !data.repayments.some((r) => r.transaction_id === t.id)
              );
              const opts = (sign: number) =>
                eligible
                  .filter((t) => Number(t.amount) * sign > 0)
                  .map((t) => ({
                    value: t.id,
                    label: t.label + " - " + money(t.amount) + " - " + accountName(t.account_id)
                  }));
              if (!opts(-1).length || !opts(1).length) {
                setError(
                  "Le rapprochement nécessite une entrée et une sortie parmi les opérations affichées"
                );
                return;
              }
              setEdit({
                resource: "",
                endpoint: "/transfers/link",
                title: "Rapprocher un virement importé",
                fields: [
                  {
                    name: "debit_id",
                    label: "Écriture débitée",
                    options: opts(-1)
                  },
                  {
                    name: "credit_id",
                    label: "Écriture créditée",
                    options: opts(1)
                  }
                ]
              });
            }}
          >
            Rapprocher un virement
          </button>
          <button
            className="primary"
            onClick={() => open("transactions")}
            disabled={!data.accounts.length}
          >
            + Ajouter une opération
          </button>
        </div>
      </div>
      <div className="operation-filters">
        <label>
          Rechercher
          <input
            placeholder="Libellé de l’opération"
            value={search}
            maxLength={100}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <label>
          Catégorie
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setPage(1);
            }}
          >
            <option value="">Toutes les catégories</option>
            {categoryOpts.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted">
        {data.transaction_count} opération
        {data.transaction_count > 1 ? "s" : ""} pour cette sélection
      </p>
      <section className="panel table-panel">{transactions()}</section>
      <div className="pagination">
        <button disabled={page === 1 || loading} onClick={() => setPage(page - 1)}>
          Précédent
        </button>
        <span>
          Page {page} sur {Math.max(1, Math.ceil(data.transaction_count / 50))}
        </span>
        <button
          disabled={page * 50 >= data.transaction_count || loading}
          onClick={() => setPage(page + 1)}
        >
          Suivant
        </button>
      </div>
      <details className="panel">
        <summary>Catégories et règles de classement</summary>
        <div className="two-columns">
          <section>
            <div className="section-head">
              <h3>Catégories</h3>
              <button onClick={() => open("categories")}>+ Ajouter</button>
            </div>
            {data.categories.map((c) => (
              <div className="management-row" key={c.id}>
                <span>
                  {c.name}
                  <small>{c.kind}</small>
                </span>
                {editButtons("categories", c)}
              </div>
            ))}
          </section>
          <section>
            <div className="section-head">
              <h3>Règles</h3>
              <button onClick={() => open("rules")} disabled={!data.categories.length}>
                + Ajouter
              </button>
            </div>
            <p className="muted">
              {"La première règle correspondante classe les nouvelles opérations. Le classement manuel reste " +
                "prioritaire."}
            </p>
            {data.rules.map((r) => (
              <div className="management-row" key={r.id}>
                <span>
                  « {r.contains} » → {catName(r.category_id)}
                </span>
                {editButtons("rules", r)}
              </div>
            ))}
            <button
              disabled={busy}
              onClick={async () => {
                const result = await act("/rules/apply");
                if (result) setNotice(result.count + " opérations classées");
              }}
            >
              Classer les opérations sans catégorie
            </button>
          </section>
        </div>
      </details>
    </>
  );
}
