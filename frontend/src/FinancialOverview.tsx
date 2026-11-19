import { money, day } from "./api";
import type { Data, Item } from "./types";
import { Empty, Metric, HistoryChart } from "./components";

import type * as React from "react";

import type { Analysis } from "./types";

type FinancialOverviewProps = {
  open: (
    resource: string,
    item?: Item | undefined,
    extra?: Record<string, unknown> | undefined
  ) => void;
  a: Analysis;
  today: string;
  selectTab: (next: string) => void;
  data: Data;
  account: string;
  accountName: (id: number) => string;
  transactions: (compact?: boolean) => React.JSX.Element;
};

export function FinancialOverview({
  open,
  a,
  today,
  selectTab,
  data,
  account,
  accountName,
  transactions
}: FinancialOverviewProps) {
  return (
    <>
      <div className="section-head">
        <h2>La situation en un regard</h2>
        <button className="primary" onClick={() => open("transactions")}>
          + Ajouter une opération
        </button>
      </div>
      <div className="metrics">
        <Metric label="Solde des comptes" value={money(a.balance)} note={"Au " + day(today)} />
        <Metric
          label="Revenus du mois"
          value={money(a.income)}
          note="Hors virements internes"
          positive
        />
        <Metric label="Dépenses du mois" value={money(a.spending)} note="Opérations enregistrées" />
        <Metric
          label="Solde du mois"
          value={money(a.net)}
          note="Revenus moins dépenses"
          positive={a.net >= 0}
        />
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="section-head">
            <h2>Revenus et dépenses</h2>
            <button className="text-button" onClick={() => selectTab("chart")}>
              Voir les analyses
            </button>
          </div>
          <HistoryChart rows={a.history} />
        </section>
        <section className="panel">
          <h2>Les prochaines échéances</h2>
          <div className="due-list">
            {data.recurring
              .filter((r) => r.active && (!account || r.account_id === Number(account)))
              .sort((x, y) => x.next_due.localeCompare(y.next_due))
              .slice(0, 4)
              .map((r) => (
                <div className="due-item" key={r.id}>
                  <span className="due-date">
                    <strong>{r.next_due.slice(8)}</strong>
                    {new Date(r.next_due + "T12:00:00").toLocaleDateString("fr-FR", {
                      month: "short"
                    })}
                  </span>
                  <div>
                    <strong>{r.name}</strong>
                    <small>{accountName(r.account_id)}</small>
                  </div>
                  <span className="amount">{money(r.amount)}</span>
                </div>
              ))}
          </div>
          {!data.recurring.length && <Empty>Aucune échéance enregistrée.</Empty>}
          <button className="text-button" onClick={() => selectTab("calendar")}>
            Toutes les échéances →
          </button>
        </section>
      </div>
      <section className="panel">
        <div className="section-head">
          <h2>Les dernières opérations</h2>
          <button className="text-button" onClick={() => selectTab("transactions")}>
            Toutes les opérations →
          </button>
        </div>
        {transactions(true)}
      </section>
    </>
  );
}
