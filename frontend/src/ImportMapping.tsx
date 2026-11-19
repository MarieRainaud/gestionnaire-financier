import type * as React from "react";

import type { Dispatch } from "react";
import type { SetStateAction } from "react";

type ImportMappingProps = {
  layout: string;
  setLayout: React.Dispatch<React.SetStateAction<string>>;
  invalidate: () => void;
  dayFirst: boolean;
  setDayFirst: React.Dispatch<React.SetStateAction<boolean>>;
  column: (
    name: "date_column" | "label_column" | "amount_column" | "debit_column" | "credit_column",
    label: string,
    optional?: boolean
  ) => React.JSX.Element;
  headers: string[];
  sample: Record<string, unknown>[];
  busy: boolean;
  upload: (scan?: boolean) => Promise<void>;
};

export function ImportMapping({
  layout,
  setLayout,
  invalidate,
  dayFirst,
  setDayFirst,
  column,
  headers,
  sample,
  busy,
  upload
}: ImportMappingProps) {
  return (
    <>
      <h3 className="step-title">2 - Associer les colonnes</h3>
      <div className="two-columns">
        <label className="field">
          Présentation des montants
          <select
            value={layout}
            onChange={(e) => {
              setLayout(e.target.value);
              invalidate();
            }}
          >
            <option value="signed">Une colonne de montants signés</option>
            <option value="split">Une colonne de débit et une de crédit</option>
          </select>
        </label>
        <label className="field">
          Ordre des dates
          <select
            value={String(dayFirst)}
            onChange={(e) => {
              setDayFirst(e.target.value === "true");
              invalidate();
            }}
          >
            <option value="true">Jour / mois / année</option>
            <option value="false">Mois / jour / année</option>
          </select>
        </label>
        {column("date_column", "Date de l’opération")}
        {column("label_column", "Libellé de l’opération")}
        {layout === "signed" ? (
          column("amount_column", "Montant signé")
        ) : (
          <>
            {column("debit_column", "Débit")}
            {column("credit_column", "Crédit")}
          </>
        )}
      </div>
      <details>
        <summary>Aperçu du fichier d’origine</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {headers.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sample.map((r, i) => (
                <tr key={i}>
                  {headers.map((h) => (
                    <td key={h}>{String(r[h] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <button className="primary" disabled={busy} onClick={() => upload()}>
        Contrôler les opérations
      </button>
    </>
  );
}
