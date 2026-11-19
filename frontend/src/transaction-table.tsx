import { money, day } from "./api";
import type { Data, Item } from "./types";
import { Empty } from "./components";

import type * as React from "react";

type TransactionsContext = {
  data: Data | null;
  today: string;
  accountName: (id: number) => string;
  catName: (id: number | null) => string;
  busy: boolean;
  act: (
    path: string,
    body?: unknown,
    method?: string
  ) => Promise<Record<string, unknown> | undefined>;
  remove: (resource: string, item: Item) => Promise<void>;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
};
export function renderTransactions(
  { data, today, accountName, catName, busy, act, remove, editButtons }: TransactionsContext,
  compact = false
) {
  const rows = compact ? data?.transactions.slice(0, 5) : data?.transactions;
  return rows?.length ? (
    <div className="table-scroll">
      <table className={"transactions-table " + (compact ? "compact" : "")}>
        <thead>
          <tr>
            <th>Date</th>
            <th>Opération</th>
            <th>Catégorie</th>
            <th className="right">Montant</th>
            {!compact && (
              <th>
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <td className="nowrap">
                {day(t.date)}
                {t.date > today && <small>Prévue</small>}
              </td>
              <td>
                <strong>{t.label}</strong>
                <small>{accountName(t.account_id)}</small>
              </td>
              <td>
                <span className={"tag " + (t.transfer ? "transfer" : "")}>
                  {t.transfer ? "Virement interne" : catName(t.category_id)}
                </span>
              </td>
              <td className={"right amount " + (Number(t.amount) > 0 ? "positive" : "")}>
                {money(t.amount)}
              </td>
              {!compact && (
                <td>
                  {t.transfer ? (
                    <div className="row-actions">
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => act("/transfers/" + t.id + "/link", undefined, "DELETE")}
                      >
                        Dissocier
                      </button>
                      <button
                        className="text-button danger"
                        disabled={busy}
                        onClick={() => remove("transactions", t)}
                      >
                        Supprimer le virement
                      </button>
                    </div>
                  ) : t.recurring_id ? (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => act("/recurring-payments/" + t.id, undefined, "DELETE")}
                    >
                      Dissocier de l’échéance
                    </button>
                  ) : data?.repayments.some((r) => r.transaction_id === t.id) ? (
                    <span className="muted">Liée à un prêt</span>
                  ) : (
                    editButtons("transactions", t)
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty>Aucune opération pour cette sélection.</Empty>
  );
}
