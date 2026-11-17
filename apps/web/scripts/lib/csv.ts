/** RFC 4180 reader: quotes, embedded newlines, CRLF, BOM, and rectangular rows. */
export function parseCsv(input: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false, closed = false;
  const source = input.replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index++) {
    const character = source.charAt(index);
    if (quoted) {
      if (character === '"') {
        if (source[index + 1] === '"') { field += '"'; index++; }
        else { quoted = false; closed = true; }
      } else field += character;
    } else if (character === '"') {
      if (field !== "" || closed) throw new Error("Invalid quote in CSV.");
      quoted = true;
    } else if (character === ",") {
      row.push(field); field = ""; closed = false;
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && source[index + 1] === "\n") index++;
      row.push(field); rows.push(row); row = []; field = ""; closed = false;
    } else {
      if (closed) throw new Error("Unexpected character after CSV quote.");
      field += character;
    }
  }
  if (quoted) throw new Error("Unterminated CSV quote.");
  if (field !== "" || row.length > 0 || closed) { row.push(field); rows.push(row); }
  const headers = rows.shift();
  if (!headers || new Set(headers).size !== headers.length || headers.some((header) => header === "")) throw new Error("CSV needs unique, nonempty headers.");
  return rows.map((values, index) => {
    if (values.length !== headers.length) throw new Error(`CSV row ${String(index + 2)} has ${String(values.length)} columns; expected ${String(headers.length)}.`);
    return Object.fromEntries(headers.map((header, column) => [header, values[column] ?? ""]));
  });
}

export function encodeCsv(headers: string[], rows: Record<string, string>[]): string {
  const quote = (value: string) => /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
  return `${[headers, ...rows.map((row) => headers.map((header) => row[header] ?? ""))].map((row) => row.map(quote).join(",")).join("\n")}\n`;
}
