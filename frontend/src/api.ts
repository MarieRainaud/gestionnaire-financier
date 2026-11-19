export const API_BASE = /^\/demo\/?$/.test(window.location.pathname) ? "/demo/api" : "/api";

export async function api<T = Record<string, unknown>>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Requested-With", "finance");
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(API_BASE + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/login") window.dispatchEvent(new Event("finance-session-expired"));
    const body = await response
      .json()
      .catch(() => ({ detail: "Le serveur est momentanément indisponible" }));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Champs manquants ou non valides",
    );
  }
  return response.json();
}
export const money = (n: number | string) =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(
    Number(n),
  );
export const day = (d: string) =>
  new Date(d + "T12:00:00").toLocaleDateString("fr-FR");
export const monthName = (d: string, short = false) =>
  new Date(d.slice(0, 7) + "-01T12:00:00").toLocaleDateString("fr-FR", {
    month: short ? "short" : "long",
    ...(short ? {} : { year: "numeric" }),
  });
