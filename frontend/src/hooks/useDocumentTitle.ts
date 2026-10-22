import { useEffect } from "react";

const SITE = "Chess Review Lab";

/** Sets the browser tab / screen-reader page title: "<page> – Chess Review Lab". */
export function useDocumentTitle(page: string | null | undefined) {
  useEffect(() => {
    document.title = page ? `${page} – ${SITE}` : SITE;
  }, [page]);
}
