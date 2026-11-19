import { money, day } from "./api";
import type { Data, Item } from "./types";
import { Empty } from "./components";

import type * as React from "react";

import type { Analysis } from "./types";

type FinancialLoansProps = {
  open: (
    resource: string,
    item?: Item | undefined,
    extra?: Record<string, unknown> | undefined
  ) => void;
  data: Data;
  a: Analysis;
  repay: (loan: Item) => void;
  matchLoan: (loan: Item) => void;
  busy: boolean;
  act: (
    path: string,
    body?: unknown,
    method?: string
  ) => Promise<Record<string, unknown> | undefined>;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
};

export function FinancialLoans({
  open,
  data,
  a,
  repay,
  matchLoan,
  busy,
  act,
  editButtons
}: FinancialLoansProps) {
  return (
    <>
      <div className="section-head">
        <h2>Les prêts et remboursements</h2>
        <button className="primary" onClick={() => open("loans")}>
          + Ajouter un prêt
        </button>
      </div>
      <p className="muted">
        {"Le total contractuel inclut les intérêts et frais prévus. Le solde restant correspond à ce total " +
          "moins les remboursements enregistrés."}
      </p>
      {!data.loans.length && <Empty>Aucun prêt enregistré.</Empty>}
      <div className="loan-grid">
        {data.loans.map((l) => {
          const info = a.loans.find((x) => x.id === l.id)!;
          return (
            <article className="panel" key={l.id}>
              <span className="eyebrow">{l.lender}</span>
              <h3>{l.name}</h3>
              <div className="loan-remaining">
                <strong>{money(info.remaining)}</strong>
                <span>restant à rembourser</span>
              </div>
              <progress value={info.paid} max={Number(l.total_due)} aria-label="Part remboursée" />
              <p className="muted">
                {money(info.paid)} remboursés sur {money(l.total_due)}
              </p>
              <dl>
                <div>
                  <dt>Capital emprunté</dt>
                  <dd>{money(l.principal)}</dd>
                </div>
                <div>
                  <dt>Mensualité</dt>
                  <dd>{money(l.installment)}</dd>
                </div>
                <div>
                  <dt>Prochaine échéance</dt>
                  <dd>{info.remaining > 0 ? day(l.next_due) : "Prêt remboursé"}</dd>
                </div>
              </dl>
              <div className="actions">
                <button
                  className="primary"
                  onClick={() => repay(l)}
                  disabled={info.remaining <= 0 || !data.accounts.length}
                >
                  Enregistrer un remboursement
                </button>
                <button onClick={() => matchLoan(l)} disabled={info.remaining <= 0}>
                  Rattacher une opération
                </button>
              </div>
              <details>
                <summary>Échéancier prévisionnel</summary>
                <div className="schedule">
                  {info.schedule.slice(0, 120).map((p) => (
                    <div className="management-row" key={p.date}>
                      <span>{day(p.date)}</span>
                      <span>{money(p.amount)}</span>
                    </div>
                  ))}
                </div>
                <p className="muted">
                  Échéances mensuelles calculées sur le total contractuel restant.
                </p>
              </details>
              <details>
                <summary>Remboursements enregistrés</summary>
                {data.repayments
                  .filter((r) => r.loan_id === l.id)
                  .map((r) => (
                    <div className="management-row" key={r.id}>
                      <span>Opération n° {r.transaction_id}</span>
                      <button
                        className="text-button danger"
                        disabled={busy}
                        onClick={() => {
                          if (
                            confirm(
                              "Dissocier le remboursement en conservant l’opération bancaire ?"
                            )
                          )
                            act("/repayments/" + r.id, undefined, "DELETE");
                        }}
                      >
                        Dissocier
                      </button>
                    </div>
                  ))}
              </details>
              {editButtons("loans", l)}
            </article>
          );
        })}
      </div>
    </>
  );
}
