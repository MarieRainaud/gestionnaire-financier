import { ImportMapping } from "./ImportMapping";
import { ImportPreview } from "./ImportPreview";
import { useState } from "react";
import type { Data } from "./types";
import { api } from "./api";

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
export function ImportPage({
  mode,
  data,
  onImported
}: {
  mode: string;
  data: Data;
  onImported: (message: string) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null),
    [account, setAccount] = useState(String(data.accounts[0]?.id || ""));
  const [columns, setColumns] = useState({
    date_column: "",
    label_column: "",
    amount_column: "",
    debit_column: "",
    credit_column: ""
  });
  const [layout, setLayout] = useState("signed"),
    [dayFirst, setDayFirst] = useState(true);
  const [headers, setHeaders] = useState<string[]>([]),
    [sample, setSample] = useState<Record<string, unknown>[]>([]),
    [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [partial, setPartial] = useState(false),
    [allowIdentical, setAllowIdentical] = useState(false);
  function invalidate() {
    setPreview(null);
    setPartial(false);
    setAllowIdentical(false);
  }
  async function upload(scan = false) {
    if (!file || !account) return;
    setBusy(true);
    setError("");
    invalidate();
    const form = new FormData();
    form.append("file", file);
    form.append(
      "mapping",
      JSON.stringify({
        account_id: Number(account),
        ...columns,
        ...(scan ? { date_column: "" } : {}),
        ...(layout === "signed" ? { debit_column: "", credit_column: "" } : { amount_column: "" }),
        day_first: dayFirst
      })
    );
    try {
      const result = await api<Preview>("/import/preview", {
        method: "POST",
        body: form
      });
      if (scan) {
        setHeaders(result.headers || []);
        setSample(result.sample || []);
      } else setPreview(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function example() {
    setBusy(true);
    setError("");
    try {
      setPreview(await api<Preview>("/import/sample"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function commit() {
    if (!preview?.rows?.length) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ added: number; skipped: number }>(
        mode === "demo" ? "/demo/import-sample" : "/import/commit",
        {
          method: "POST",
          ...(mode === "demo"
            ? {}
            : {
                body: JSON.stringify({
                  rows: preview.rows,
                  allow_identical: allowIdentical
                })
              })
        }
      );
      invalidate();
      await onImported(
        result.added + " opérations importées - " + result.skipped + " doublons ignorés"
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const column = (name: keyof typeof columns, label: string, optional = false) => (
    <label className="field">
      {label}
      <select
        value={columns[name]}
        onChange={(e) => {
          setColumns({ ...columns, [name]: e.target.value });
          invalidate();
        }}
      >
        <option value="">{optional ? "Aucune" : "Choisir une colonne"}</option>
        {headers.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <>
      <div className="section-head">
        <h2>Importer des opérations</h2>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {mode === "demo" ? (
        <section className="panel">
          <h3>Un exemple avec des opérations fictives</h3>
          <p>
            La démonstration utilise uniquement un fichier d’exemple. Les exports bancaires
            personnels se chargent dans l’espace privé.
          </p>
          <button className="primary" disabled={busy || !data.accounts.length} onClick={example}>
            Prévisualiser le fichier d’exemple
          </button>
        </section>
      ) : (
        <section className="panel">
          <h3>1 - Choisir le compte et le fichier</h3>
          <p className="muted">
            CSV ou XLSX, jusqu’à 5 Mo et 10 000 lignes. Le fichier est traité en mémoire et n’est
            pas conservé.
          </p>
          <div className="two-columns">
            <label className="field">
              Compte destinataire
              <select
                value={account}
                onChange={(e) => {
                  setAccount(e.target.value);
                  invalidate();
                }}
              >
                <option value="">Choisir un compte</option>
                {data.accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Export bancaire
              <input
                type="file"
                accept=".csv,.xlsx"
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  setFile(f);
                  setHeaders([]);
                  setSample([]);
                  invalidate();
                  setError(
                    f && f.size > 5 * 1024 * 1024 ? "Fichier trop volumineux, limite de 5 Mo" : ""
                  );
                }}
              />
            </label>
          </div>
          {!data.accounts.length && <p>Un compte doit être ajouté avant le premier import.</p>}
          <button
            disabled={!file || !account || busy || (file?.size || 0) > 5 * 1024 * 1024}
            onClick={() => upload(true)}
          >
            {busy ? "Lecture en cours…" : "Lire les colonnes du fichier"}
          </button>
          {headers.length > 0 && (
            <ImportMapping
              layout={layout}
              setLayout={setLayout}
              invalidate={invalidate}
              dayFirst={dayFirst}
              setDayFirst={setDayFirst}
              column={column}
              headers={headers}
              sample={sample}
              busy={busy}
              upload={upload}
            />
          )}
        </section>
      )}
      {preview && (
        <ImportPreview
          mode={mode}
          preview={preview}
          partial={partial}
          setPartial={setPartial}
          allowIdentical={allowIdentical}
          setAllowIdentical={setAllowIdentical}
          invalidate={invalidate}
          busy={busy}
          commit={commit}
        />
      )}
    </>
  );
}
