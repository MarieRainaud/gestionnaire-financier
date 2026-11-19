import { RecurringSchedule } from "./RecurringSchedule";
import { money, day } from "./api";
import type { Data, Edit, Item } from "./types";
import { Empty, Metric } from "./components";

import type * as React from "react";

import type { Analysis } from "./types";
import type { Dispatch } from "react";
import type { SetStateAction } from "react";

type FinancialRecurringProps = {
  open: (
    resource: string,
    item?: Item | undefined,
    extra?: Record<string, unknown> | undefined
  ) => void;
  data: Data;
  a: Analysis;
  accountName: (id: number) => string;
  today: string;
  busy: boolean;
  act: (
    path: string,
    body?: unknown,
    method?: string
  ) => Promise<Record<string, unknown> | undefined>;
  setError: React.Dispatch<React.SetStateAction<string>>;
  setEdit: React.Dispatch<React.SetStateAction<Edit | null>>;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
};

export function FinancialRecurring({
  open,
  data,
  a,
  accountName,
  today,
  busy,
  act,
  setError,
  setEdit,
  editButtons
}: FinancialRecurringProps) {
  return (
    <>
      <div className="section-head">
        <h2>Abonnements et échéances</h2>
        <button
          className="primary"
          onClick={() => open("recurring")}
          disabled={!data.accounts.length}
        >
          + Ajouter une échéance
        </button>
      </div>
      <div className="metrics three">
        <Metric
          label="Charges fixes mensualisées"
          value={money(
            data.recurring
              .filter((r) => r.active && Number(r.amount) < 0)
              .reduce((s, r) => s - Number(r.amount) / r.months, 0)
          )}
          note="Les dépenses annuelles sont lissées"
        />
        <Metric
          label="Échéances actives"
          value={String(data.recurring.filter((r) => r.active).length)}
        />
        <Metric
          label="À confirmer"
          value={String(a.suggestions.length)}
          note="Dépenses régulières détectées"
        />
      </div>
      <RecurringSchedule
        data={data}
        accountName={accountName}
        today={today}
        busy={busy}
        act={act}
        setError={setError}
        setEdit={setEdit}
        editButtons={editButtons}
      />
      <details className="panel">
        <summary>Règlements rattachés aux échéances</summary>
        {data.recurring_payments.length ? (
          data.recurring_payments.map((t) => (
            <div className="management-row" key={t.id}>
              <span>
                {day(t.date)} - {t.label}
                <small>{money(t.amount)}</small>
              </span>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => act("/recurring-payments/" + t.id, undefined, "DELETE")}
              >
                Dissocier en conservant l’opération
              </button>
            </div>
          ))
        ) : (
          <p className="muted">Aucun règlement rattaché.</p>
        )}
      </details>
      <section className="panel">
        <h2>Dépenses régulières à confirmer</h2>
        <p className="muted">
          {"Au moins trois dépenses de libellé identique, proches d’un mois et d’un montant stable. Une " +
            "suggestion reste à vérifier."}
        </p>
        {a.suggestions.length ? (
          a.suggestions.map((s, i) => (
            <div className="management-row" key={i}>
              <span>
                <strong>{s.name}</strong>
                <small>
                  {s.occurrences} occurrences - {money(s.amount)} par mois
                </small>
              </span>
              <button
                onClick={() =>
                  open("recurring", undefined, {
                    ...s,
                    next_due: s.next_due < today ? today : s.next_due
                  })
                }
              >
                Créer une échéance
              </button>
            </div>
          ))
        ) : (
          <Empty>Aucune nouvelle dépense régulière détectée.</Empty>
        )}
      </section>
    </>
  );
}
