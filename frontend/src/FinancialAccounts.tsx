import { money, day } from "./api";
import type { Data, Item } from "./types";
import { Icon, Empty } from "./components";

import type * as React from "react";

import type { Analysis } from "./types";
import type { Dispatch } from "react";
import type { SetStateAction } from "react";

type FinancialAccountsProps = {
  transfer: () => void;
  data: Data;
  open: (
    resource: string,
    item?: Item | undefined,
    extra?: Record<string, unknown> | undefined
  ) => void;
  a: Analysis;
  today: string;
  setAccount: React.Dispatch<React.SetStateAction<string>>;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  selectTab: (next: string) => void;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
};

export function FinancialAccounts({
  transfer,
  data,
  open,
  a,
  today,
  setAccount,
  setPage,
  selectTab,
  editButtons
}: FinancialAccountsProps) {
  return (
    <>
      <div className="section-head">
        <h2>Les comptes</h2>
        <div className="actions">
          <button onClick={transfer} disabled={data.accounts.length < 2}>
            Virement entre comptes
          </button>
          <button className="primary" onClick={() => open("accounts")}>
            + Ajouter un compte
          </button>
        </div>
      </div>
      <p className="muted">
        {
          "Le solde initial correspond à la situation avant les opérations enregistrées à partir de sa date."
        }
      </p>
      <div className="account-grid">
        {data.accounts.map((acc, i) => (
          <article className="panel account-card" key={acc.id}>
            <div className="section-head">
              <span className="eyebrow">{acc.kind}</span>
              <Icon name="wallet" />
            </div>
            <h3>{acc.name}</h3>
            <p className="muted">{acc.bank}</p>
            <strong className="account-balance">{money(a.balances[String(acc.id)] || 0)}</strong>
            <small>Solde au {day(today)}</small>
            <button
              className="text-button"
              onClick={() => {
                setAccount(String(acc.id));
                setPage(1);
                selectTab("transactions");
              }}
            >
              Voir les opérations →
            </button>
            {editButtons("accounts", acc)}
          </article>
        ))}
      </div>
      {!data.accounts.length && (
        <Empty action={<button onClick={() => open("accounts")}>Ajouter un compte</button>}>
          Le suivi commence par un premier compte.
        </Empty>
      )}
    </>
  );
}
