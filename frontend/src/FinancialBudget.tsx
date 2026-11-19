import { money } from "./api";
import type { Data, Item } from "./types";
import { Empty, Metric } from "./components";

import type * as React from "react";

import type { Analysis } from "./types";

type FinancialBudgetProps = {
  open: (
    resource: string,
    item?: Item | undefined,
    extra?: Record<string, unknown> | undefined
  ) => void;
  data: Data;
  a: Analysis;
  catName: (id: number | null) => string;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
};

export function FinancialBudget({ open, data, a, catName, editButtons }: FinancialBudgetProps) {
  return (
    <>
      <div className="section-head">
        <h2>Le budget</h2>
        <button
          className="primary"
          onClick={() => open("budgets")}
          disabled={!data.categories.some((c) => c.kind === "dépense")}
        >
          + Ajouter un poste
        </button>
      </div>
      <div className="metrics three">
        <Metric label="Budget prévu" value={money(a.budgets.reduce((s, b) => s + b.amount, 0))} />
        <Metric
          label="Dépenses sur ces postes"
          value={money(a.budgets.reduce((s, b) => s + b.actual, 0))}
        />
        <Metric
          label="Disponible sur ces postes"
          value={money(a.budget_remaining)}
          positive={a.budget_remaining >= 0}
        />
      </div>
      <p className="muted">
        {
          "Tous les comptes sont inclus. Les dépenses sans poste budgétaire restent visibles dans les analyses."
        }
      </p>
      <section className="panel">
        {a.budgets.length ? (
          a.budgets.map((b) => (
            <div className="budget-row" key={b.id}>
              <div className="section-head">
                <h3>{catName(b.category_id)}</h3>
                <span className={b.remaining < 0 ? "negative" : ""}>
                  {money(b.actual)} <span className="muted">sur {money(b.amount)}</span>
                </span>
              </div>
              <progress
                value={Math.min(b.actual, b.amount)}
                max={b.amount}
                aria-label={catName(b.category_id)}
              />
              <div className="section-head">
                <span className={b.remaining < 0 ? "negative" : "muted"}>
                  {b.remaining < 0
                    ? "Dépassement de " + money(-b.remaining)
                    : money(b.remaining) + " disponibles"}
                </span>
                {editButtons(
                  "budgets",
                  data.budgets.find((x) => x.id === b.id)!
                )}
              </div>
            </div>
          ))
        ) : (
          <Empty>Aucun poste budgétaire pour ce mois.</Empty>
        )}
      </section>
    </>
  );
}
