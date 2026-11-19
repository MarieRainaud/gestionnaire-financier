import { money, day } from "./api";
import type { Data, Edit, Item } from "./types";

import type * as React from "react";
import type { Dispatch } from "react";
import type { SetStateAction } from "react";

import type { Recurring } from "./types";

type RecurringRowProps = {
  r: Recurring;
  accountName: (id: number) => string;
  today: string;
  busy: boolean;
  act: (
    path: string,
    body?: unknown,
    method?: string | undefined
  ) => Promise<Record<string, unknown> | undefined>;
  data: Data;
  setError: React.Dispatch<React.SetStateAction<string>>;
  setEdit: React.Dispatch<React.SetStateAction<Edit | null>>;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
};

export function RecurringRow({
  r,
  accountName,
  today,
  busy,
  act,
  data,
  setError,
  setEdit,
  editButtons
}: RecurringRowProps) {
  return (
    <tr key={r.id}>
      <td>
        <strong>{r.name}</strong>
        <small>
          {accountName(r.account_id)}
          {!r.active && " - Suspendue"}
        </small>
      </td>
      <td>
        <span className={r.active && r.next_due < today ? "negative" : ""}>{day(r.next_due)}</span>
      </td>
      <td>
        {r.months === 1
          ? "Mensuelle"
          : r.months === 12
            ? "Annuelle"
            : "Tous les " + r.months + " mois"}
      </td>
      <td className="right amount">{money(r.amount)}</td>
      <td>
        <div className="row-actions">
          {r.active && r.next_due <= today && (
            <button
              className="text-button"
              disabled={busy}
              onClick={() => {
                if (
                  confirm(
                    "Créer une opération pour cette échéance ? Une opération déjà importée doit être rattachée avec le bouton correspondant."
                  )
                )
                  act("/recurring/" + r.id + "/pay");
              }}
            >
              Enregistrer le règlement
            </button>
          )}
          <button
            className="text-button"
            onClick={() => {
              const choices = data.transactions
                .filter(
                  (t) =>
                    !t.transfer &&
                    !t.recurring_id &&
                    t.account_id === r.account_id &&
                    Number(t.amount) > 0 === Number(r.amount) > 0 &&
                    Math.abs((Date.parse(t.date) - Date.parse(r.next_due)) / 86400000) <= 15
                )
                .map((t) => ({
                  value: t.id,
                  label: day(t.date) + " - " + t.label + " - " + money(t.amount)
                }));
              if (!choices.length) {
                setError(
                  "Aucune opération compatible dans le mois affiché. Sélectionner le mois du règlement depuis les opérations."
                );
                return;
              }
              setEdit({
                resource: "",
                title: "Rattacher un règlement existant",
                endpoint: "/recurring/" + r.id + "/match",
                fields: [
                  {
                    name: "transaction_id",
                    label: "Opération existante",
                    options: choices
                  }
                ],
                initial: {
                  transaction_id: choices[0].value
                }
              });
            }}
          >
            Rattacher une opération
          </button>
        </div>
        {editButtons("recurring", r)}
      </td>
    </tr>
  );
}
