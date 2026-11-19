import { RecurringRow } from "./RecurringRow";

import type { Data, Edit, Item } from "./types";
import { Empty } from "./components";
import type * as React from "react";

import type { Dispatch } from "react";
import type { SetStateAction } from "react";

type RecurringScheduleProps = {
  data: Data;
  accountName: (id: number) => string;
  today: string;
  busy: boolean;
  act: (
    path: string,
    body?: unknown,
    method?: string | undefined
  ) => Promise<Record<string, unknown> | undefined>;
  setError: React.Dispatch<React.SetStateAction<string>>;
  setEdit: React.Dispatch<React.SetStateAction<Edit | null>>;
  editButtons: (resource: string, item: Item) => React.JSX.Element;
};

export function RecurringSchedule({
  data,
  accountName,
  today,
  busy,
  act,
  setError,
  setEdit,
  editButtons
}: RecurringScheduleProps) {
  return (
    <section className="panel table-panel">
      {data.recurring.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Échéance</th>
                <th>Prochaine date</th>
                <th>Périodicité</th>
                <th className="right">Montant</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {[...data.recurring]
                .sort((x, y) => x.next_due.localeCompare(y.next_due))
                .map((r) => (
                  <RecurringRow
                    key={r.id}
                    r={r}
                    accountName={accountName}
                    today={today}
                    busy={busy}
                    act={act}
                    data={data}
                    setError={setError}
                    setEdit={setEdit}
                    editButtons={editButtons}
                  />
                ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>Aucune échéance enregistrée.</Empty>
      )}
    </section>
  );
}
