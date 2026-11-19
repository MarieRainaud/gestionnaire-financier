import type { Data, Edit, Field, Item } from "./types";

import type * as React from "react";

type OpenContext = {
  text: (name: string, label: string, help?: string | undefined) => Field;
  number: (name: string, label: string, min?: string | undefined) => Field;
  dateField: (name: string, label: string) => Field;
  today: string;
  accountField: Field;
  catField: Field;
  accountOpts: { value: number; label: string }[];
  data: Data | null;
  month: string;
  setEdit: React.Dispatch<React.SetStateAction<Edit | null>>;
};
export function openItemEditor(
  {
    text,
    number,
    dateField,
    today,
    accountField,
    catField,
    accountOpts,
    data,
    month,
    setEdit
  }: OpenContext,
  resource: string,
  item?: Item,
  extra?: Record<string, unknown>
) {
  const defs: Record<string, { title: string; fields: Field[]; initial: Record<string, unknown> }> =
    {
      accounts: {
        title: "Compte bancaire",
        fields: [
          text("name", "Nom du compte"),
          text("bank", "Établissement"),
          {
            name: "kind",
            label: "Type de compte",
            options: ["courant", "épargne", "autre"].map((value) => ({
              value,
              label: value
            }))
          },
          number("opening", "Solde initial"),
          dateField("opening_date", "Date du solde initial")
        ],
        initial: { opening: 0, opening_date: today, kind: "courant" }
      },
      categories: {
        title: "Catégorie",
        fields: [
          text("name", "Nom"),
          {
            name: "kind",
            label: "Type",
            options: ["dépense", "revenu"].map((value) => ({
              value,
              label: value
            }))
          }
        ],
        initial: { kind: "dépense" }
      },
      transactions: {
        title: "Opération",
        fields: [
          accountField,
          dateField("date", "Date"),
          text("label", "Libellé"),
          number("amount", "Montant en euros"),
          catField
        ],
        initial: {
          account_id: accountOpts[0]?.value,
          date: today,
          amount: "",
          category_id: ""
        }
      },
      budgets: {
        title: "Poste budgétaire",
        fields: [
          {
            name: "category_id",
            label: "Catégorie de dépenses",
            options:
              data?.categories
                .filter((c) => c.kind === "dépense")
                .map((c) => ({ value: c.id, label: c.name })) || []
          },
          { name: "month", label: "Mois", type: "month" },
          number("amount", "Montant prévu", "0.01")
        ],
        initial: { month, amount: "" }
      },
      recurring: {
        title: "Échéance régulière",
        fields: [
          text("name", "Nom"),
          accountField,
          number("amount", "Montant en euros"),
          catField,
          {
            name: "months",
            label: "Périodicité",
            options: [
              { value: 1, label: "Chaque mois" },
              { value: 2, label: "Tous les 2 mois" },
              { value: 3, label: "Tous les 3 mois" },
              { value: 6, label: "Tous les 6 mois" },
              { value: 12, label: "Chaque année" }
            ]
          },
          dateField("next_due", "Prochaine échéance"),
          { name: "active", label: "Échéance active", type: "checkbox" }
        ],
        initial: {
          months: 1,
          next_due: today,
          active: true,
          account_id: accountOpts[0]?.value,
          category_id: ""
        }
      },
      loans: {
        title: "Prêt",
        fields: [
          text("name", "Nom du prêt"),
          text("lender", "Prêteur"),
          number("principal", "Capital emprunté", "0.01"),
          number("total_due", "Total contractuel à rembourser", "0.01"),
          number("installment", "Mensualité", "0.01"),
          dateField("next_due", "Prochaine échéance")
        ],
        initial: { next_due: today }
      },
      rules: {
        title: "Règle de catégorisation",
        fields: [text("contains", "Le libellé contient"), { ...catField, required: true }],
        initial: {}
      }
    };
  const def = defs[resource];
  const initial = { ...def.initial, ...item, ...extra };
  if (resource === "budgets" && item) initial.month = String(item.month).slice(0, 7);
  setEdit({
    resource,
    title: (item ? "Modifier - " : "Ajouter - ") + def.title,
    fields: def.fields,
    initial
  });
}
