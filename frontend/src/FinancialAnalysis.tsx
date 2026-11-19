import { API_BASE, money, monthName } from "./api";

import { Empty, Metric, HistoryChart } from "./components";

import type { Analysis } from "./types";

type FinancialAnalysisProps = {
  a: Analysis;
  month: string;
  today: string;
  catName: (id: number | null) => string;
  account: string;
};

export function FinancialAnalysis({ a, month, today, catName, account }: FinancialAnalysisProps) {
  return (
    <>
      <div className="section-head">
        <h2>Comprendre les mouvements</h2>
        <a className="button" href={API_BASE + "/export"} download>
          Exporter les données
        </a>
      </div>
      <div className="metrics three">
        <Metric
          label="Taux d’épargne du mois"
          value={
            a.savings_rate === null
              ? "Non calculable"
              : a.savings_rate.toLocaleString("fr-FR") + " %"
          }
          note="Solde du mois rapporté aux revenus"
        />
        <Metric
          label="Écart avec le mois précédent"
          value={(a.spending_change > 0 ? "+" : "") + money(a.spending_change)}
          note="Dépenses du mois affiché moins le mois précédent"
        />
        <Metric
          label="Opérations à classer"
          value={String(a.uncategorized)}
          note="Hors virements internes"
        />
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <h2>Comparaison sur six mois</h2>
          <HistoryChart rows={a.history} />
          <p className="muted">
            {month === today.slice(0, 7) && "Le mois en cours est incomplet. "}
            Les virements internes sont exclus des revenus et dépenses.
          </p>
        </section>
        <section className="panel">
          <h2>Répartition des dépenses</h2>
          {a.categories.length ? (
            <div className="category-chart">
              {a.categories.map((c, i) => (
                <div key={c.category_id ?? "none"}>
                  <div className="section-head">
                    <span>{catName(c.category_id)}</span>
                    <strong>{money(c.amount)}</strong>
                  </div>
                  <div className="category-track">
                    <span
                      style={{
                        width: (a.spending ? (c.amount / a.spending) * 100 : 0) + "%",
                        background: ["#68dfea", "#b6b5e8", "#e6bb83", "#9fceb8", "#d69eaa"][i % 5]
                      }}
                    />
                  </div>
                  <small>
                    {a.spending ? Math.round((c.amount / a.spending) * 100) : 0} % des dépenses
                  </small>
                </div>
              ))}
            </div>
          ) : (
            <Empty>Aucune dépense sur cette période.</Empty>
          )}
        </section>
      </div>
      <section className="panel">
        <h2>Projection de trésorerie sur trois mois</h2>
        <p className="muted">
          {"Projection à partir du solde actuel, des opérations futures, des échéances actives et des prêts. " +
            "Les achats variables à venir ne sont pas estimés. Les échéances en retard sont incluses au premier " +
            "mois."}
        </p>
        <div className="projection-grid">
          {a.projection.map((p) => (
            <div key={p.month}>
              <span>{monthName(p.month)}</span>
              <strong className={p.balance < 0 ? "negative" : ""}>{money(p.balance)}</strong>
              <small>{money(p.flows)} de mouvements prévus</small>
            </div>
          ))}
        </div>
        {account && (
          <p className="muted">
            {"Les prêts sans compte de remboursement défini ne figurent que dans la projection de tous les " +
              "comptes."}
          </p>
        )}
      </section>
      <section className="panel">
        <h2>Prévu et réellement dépensé</h2>
        <p className="muted">Comparaison budgétaire sur tous les comptes.</p>
        {a.budgets.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Catégorie</th>
                  <th>Prévu</th>
                  <th>Réel</th>
                  <th>Disponible</th>
                </tr>
              </thead>
              <tbody>
                {a.budgets.map((b) => (
                  <tr key={b.id}>
                    <td>{catName(b.category_id)}</td>
                    <td>{money(b.amount)}</td>
                    <td>{money(b.actual)}</td>
                    <td className={b.remaining < 0 ? "negative" : "positive"}>
                      {money(b.remaining)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>Aucun budget défini pour ce mois.</Empty>
        )}
      </section>
    </>
  );
}
