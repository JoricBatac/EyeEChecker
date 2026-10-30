import { File } from 'expo-file-system';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';

import { deleteFile } from './check';

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (s: string) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');

/** The report templates use a small Markdown subset: #, ##, - bullets, **bold**. */
export function markdownToHtml(md: string): string {
  const out: string[] = [];
  let inList = false;
  for (const raw of md.split('\n')) {
    const line = raw.trimEnd();
    const bullet = line.startsWith('- ');
    if (inList && !bullet) {
      out.push('</ul>');
      inList = false;
    }
    if (line.startsWith('# ')) out.push(`<h1>${inline(line.slice(2))}</h1>`);
    else if (line.startsWith('## ')) out.push(`<h2>${inline(line.slice(3))}</h2>`);
    else if (bullet) {
      if (!inList) out.push('<ul>');
      inList = true;
      out.push(`<li>${inline(line.slice(2))}</li>`);
    } else if (line) out.push(`<p>${inline(line)}</p>`);
  }
  if (inList) out.push('</ul>');
  return out.join('\n');
}

export async function photosHtml(photos: { label: string; uri: string }[]): Promise<string> {
  if (!photos.length) return '';
  const cells = await Promise.all(
    photos.map(async (p) => {
      const b64 = await new File(p.uri).base64();
      return `<figure><img src="data:image/jpeg;base64,${b64}"/><figcaption>${esc(p.label)}</figcaption></figure>`;
    }),
  );
  return `<h2>Photos</h2><div class="photos">${cells.join('')}</div>`;
}

const CSS = `
  body { font-family: -apple-system, Roboto, Helvetica, sans-serif; font-size: 12pt; color: #14171a; margin: 28px; }
  h1 { font-size: 18pt; margin: 0 0 8px; } h2 { font-size: 13pt; margin: 16px 0 6px; }
  ul { margin: 4px 0 4px 18px; padding: 0; } p { margin: 4px 0; }
  .photos { display: flex; flex-wrap: wrap; gap: 10px; }
  figure { margin: 0; width: 48%; } img { width: 100%; border-radius: 6px; } figcaption { font-size: 9pt; color: #5f6670; }
  .footer { margin-top: 24px; font-size: 9pt; color: #5f6670; border-top: 1px solid #dde1e6; padding-top: 6px; }
`;

/** Build the PDF on the phone, open the share sheet, then delete the file. */
export async function shareReportPdf(title: string, markdown: string, extraHtml: string, footer: string) {
  const html = `<html><head><meta charset="utf-8"/><style>${CSS}</style></head><body>${markdownToHtml(markdown)}${extraHtml}<div class="footer">${esc(footer)}</div></body></html>`;
  const { uri } = await Print.printToFileAsync({ html });
  try {
    await Sharing.shareAsync(uri, { mimeType: 'application/pdf', UTI: 'com.adobe.pdf', dialogTitle: title });
  } finally {
    deleteFile(uri);
  }
}

export async function printReport(markdown: string, extraHtml: string, footer: string) {
  const html = `<html><head><meta charset="utf-8"/><style>${CSS}</style></head><body>${markdownToHtml(markdown)}${extraHtml}<div class="footer">${esc(footer)}</div></body></html>`;
  await Print.printAsync({ html });
}
