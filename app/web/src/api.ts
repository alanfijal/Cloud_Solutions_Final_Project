let credential = "";
export function connect(key: string) {
  credential = key;
}
export function disconnect() {
  credential = "";
}
export async function request<T>(path: string, body?: unknown): Promise<T> {
  const key = credential;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (!key || key !== credential) throw new Error("Workspace disconnected");
    try {
      const result = await fetch("/dashboard/" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          Authorization: "Bearer " + key,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.timeout(20000),
        cache: "no-store",
      });
      const data = await result.json();
      if ([429, 500, 502, 503, 504].includes(result.status) && attempt < 2) {
        await new Promise((resolve) =>
          setTimeout(resolve, 500 * 2 ** attempt + Math.random() * 250),
        );
        continue;
      }
      if (!result.ok)
        throw new Error(data.error || "The request could not be completed");
      if (key !== credential) throw new Error("Workspace disconnected");
      return data as T;
    } catch (error) {
      if (error instanceof TypeError && attempt < 2) {
        await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
        continue;
      }
      throw error;
    }
  }
  throw new Error("The service is busy. Try again shortly.");
}
export function csv(filename: string, rows: (string | number | null)[][]) {
  const encoded = rows
    .map((row) =>
      row
        .map((value) => {
          let text = String(value ?? "");
          if (
            typeof value === "string" &&
            /^[=+@\-\t\r]/.test(text.trimStart()) &&
            !/^-\d+(\.\d+)?$/.test(text)
          )
            text = "'" + text;
          return '"' + text.replaceAll('"', '""') + '"';
        })
        .join(","),
    )
    .join("\r\n");
  const url = URL.createObjectURL(
    new Blob([encoded], { type: "text/csv;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
