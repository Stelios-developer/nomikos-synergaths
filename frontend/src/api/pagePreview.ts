/** Keep document excerpts in the request body, not in URL/access logs. */
export function pagePreviewRequest(baseUrl: string, filename: string, page: number, snippet: string): { url: string; init: RequestInit } {
  return {
    url: `${baseUrl}/documents/${encodeURIComponent(filename)}/page`,
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ page, snippet }) },
  }
}
