import { money, day } from "./api";
import { Empty } from "./components";
import type * as React from "react";

import type { Dispatch } from "react";
import type { SetStateAction } from "react";
type ImportRow = {
  account_id: number;
  category_id: number | null;
  date: string;
  label: string;
  amount: string;
  fingerprint: string;
};
type Preview = {
  headers?: string[];
  sample?: Record<string, unknown>[];
  rows?: ImportRow[];
  errors?: { line: number | string; message: string }[];
  duplicates?: number;
  count: number;
};

type ImportPreviewProps = {
  mode: string;
  preview: Preview;
  partial: boolean;
  setPartial: React.Dispatch<React.SetStateAction<boolean>>;
  allowIdentical: boolean;
  setAllowIdentical: React.Dispatch<React.SetStateAction<boolean>>;
  invalidate: () => void;
  busy: boolean;
  commit: () => Promise<void>;
};

export function ImportPreview({
  mode,
  preview,
  partial,
  setPartial,
  allowIdentical,
  setAllowIdentical,
  invalidate,
  busy,
  commit
}: ImportPreviewProps) {
  return (
    <section className="panel">
      <h3>{mode === "demo" ? "Aperçu de l’exemple" : "3 - Vérifier et importer"}</h3>
      <div className="import-summary">
        <span>{preview.count} lignes lues</span>
        <span>{preview.rows?.length || 0} lignes valides</span>
        <span>{preview.duplicates || 0} doublons probables</span>
        <span>{preview.errors?.length || 0} lignes à corriger</span>
      </div>
      <p className="muted">
        Le contrôle des doublons compare le compte, la date, le libellé, le montant et le nombre
        d’occurrences identiques. Des exports qui se recouvrent partiellement peuvent nécessiter une
        vérification.
      </p>
      {!!preview.errors?.length && (
        <>
          <div className="error">
            <strong>Lignes à corriger</strong>
            <ul>
              {preview.errors.slice(0, 30).map((e, i) => (
                <li key={i}>
                  Ligne {e.line} - {e.message}
                </li>
              ))}
            </ul>
          </div>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={partial}
              onChange={(e) => setPartial(e.target.checked)}
            />
            Importer seulement les lignes valides et laisser les autres de côté
          </label>
        </>
      )}
      {preview.rows?.length ? (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Libellé</th>
                  <th className="right">Montant</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 100).map((r, i) => (
                  <tr key={i}>
                    <td>{day(r.date)}</td>
                    <td>{r.label}</td>
                    <td className="right">{money(r.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.rows.length > 100 && (
            <p className="muted">
              Aperçu des 100 premières opérations sur {preview.rows.length} lignes valides.
            </p>
          )}
          {mode !== "demo" && !!preview.duplicates && (
            <label className="checkbox-field">
              <input
                type="checkbox"
                checked={allowIdentical}
                onChange={(e) => setAllowIdentical(e.target.checked)}
              />
              Importer également les lignes déjà reconnues, après vérification des doublons
            </label>
          )}
          <div className="form-actions">
            <button onClick={invalidate} disabled={busy}>
              Annuler
            </button>
            <button
              className="primary"
              onClick={commit}
              disabled={busy || (!!preview.errors?.length && !partial)}
            >
              {busy ? "Import en cours…" : "Confirmer l’import"}
            </button>
          </div>
        </>
      ) : (
        <Empty>Aucune ligne valide à importer.</Empty>
      )}
    </section>
  );
}
