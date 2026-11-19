export type Item = {
  id: number;
  [key: string]: string | number | boolean | null;
};
export type Account = Item & {
  name: string;
  bank: string;
  opening: number;
  opening_date: string;
  kind: string;
};
export type Category = Item & { name: string; kind: string };
export type Transaction = Item & {
  account_id: number;
  category_id: number | null;
  date: string;
  label: string;
  amount: number;
  transfer: string | null;
  recurring_id: number | null;
};
export type Budget = Item & {
  category_id: number;
  month: string;
  amount: number;
};
export type Recurring = Item & {
  account_id: number;
  category_id: number | null;
  name: string;
  amount: number;
  months: number;
  next_due: string;
  active: boolean;
};
export type Loan = Item & {
  name: string;
  lender: string;
  principal: number;
  total_due: number;
  installment: number;
  next_due: string;
};
export type Rule = Item & { contains: string; category_id: number };
export type Repayment = Item & { loan_id: number; transaction_id: number };
export interface Analysis {
  balance: number;
  balances: Record<string, number>;
  income: number;
  spending: number;
  net: number;
  savings_rate: number | null;
  previous_spending: number;
  spending_change: number;
  budget_remaining: number;
  uncategorized: number;
  categories: { category_id: number | null; amount: number }[];
  history: { month: string; income: number; spending: number; net: number }[];
  budgets: {
    id: number;
    category_id: number;
    amount: number;
    actual: number;
    remaining: number;
  }[];
  loans: {
    id: number;
    paid: number;
    remaining: number;
    schedule: { date: string; amount: number }[];
  }[];
  projection: { month: string; balance: number; flows: number }[];
  suggestions: {
    name: string;
    account_id: number;
    category_id: number | null;
    amount: number;
    occurrences: number;
    next_due: string;
    months: number;
  }[];
}
export interface Data {
  accounts: Account[];
  categories: Category[];
  transactions: Transaction[];
  budgets: Budget[];
  recurring: Recurring[];
  loans: Loan[];
  rules: Rule[];
  recurring_payments: Transaction[];
  repayments: Repayment[];
  transaction_count: number;
  analysis: Analysis;
  today: string;
}
export interface Session {
  authenticated: boolean;
  mode: "demo" | "private";
  email?: string;
  display_name?:string;
  auth_mode:"local"|"oidc";
  login_url:string;
  register_url:string;
  account_url:string;
  demo_url:string;
  private_url:string;
}
export type Field = {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  options?: { value: string | number; label: string }[];
  min?: string;
  max?: string;
  help?: string;
};
export type Edit = {
  resource: string;
  title: string;
  fields: Field[];
  initial?: Record<string, unknown>;
  endpoint?: string;
  method?: string;
};
