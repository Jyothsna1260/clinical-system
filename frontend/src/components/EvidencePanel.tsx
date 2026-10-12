import { createPortal } from "react-dom";
import { useEffect, useRef } from "react";
import { getPage } from "../api/client";
import { findExcerpt } from "../lib/highlight";
import { useAsync } from "../lib/useAsync";
import { CloseIcon } from "./Icons";
import { ErrorState, LoadingState } from "./States";

export interface EvidenceTarget {
  page: number;
  excerpt: string;
  /** Context label, e.g. the criterion id the evidence supports. */
  context?: string;
}

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export function EvidencePanel({
  trialId,
  target,
  onClose,
}: {
  trialId: string;
  target: EvidenceTarget;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const markRef = useRef<HTMLElement>(null);
  const page = useAsync(() => getPage(trialId, target.page), [trialId, target.page]);

  // Focus management: focus the close button on open, restore focus on close, trap Tab.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const nodes = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
        if (nodes.length === 0) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      previous?.focus?.();
    };
  }, [onClose]);

  const text = page.data?.text ?? "";
  const match = page.data ? findExcerpt(text, target.excerpt) : null;

  // Keyed on the match position, not the match object (a new object every render), so the page only
  // scrolls when the highlighted excerpt actually changes.
  useEffect(() => {
    if (match && markRef.current) markRef.current.scrollIntoView({ block: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match?.start, match?.end, page.data]);

  // Portal to <body> so parent layout (spacing utilities, transforms) never offsets the overlay.
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-black/45 backdrop-blur-[2px]" aria-hidden="true" onClick={onClose} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
        className="relative flex h-full w-full animate-slide-in-right flex-col border-l border-slate-200 bg-surface shadow-2xl md:max-w-xl lg:max-w-2xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h2 id="evidence-title" className="text-lg font-semibold">
              Protocol evidence — page {target.page}
              {page.data ? <span className="font-normal text-slate-600"> of {page.data.page_count}</span> : null}
            </h2>
            {target.context ? <p className="text-sm text-slate-600">Cited for {target.context}</p> : null}
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="btn-ghost shrink-0 p-2" aria-label="Close evidence panel">
            <CloseIcon className="text-xl" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6" aria-live="polite">
          {page.loading ? <LoadingState label={`Loading page ${target.page}…`} /> : null}
          {!page.loading && page.error ? <ErrorState error={page.error} title="Could not load protocol page" onRetry={page.reload} /> : null}
          {!page.loading && page.data ? (
            <>
              {!match ? (
                <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                  <p className="font-semibold">Cited excerpt not located verbatim on this page.</p>
                  <p className="mt-1">The text extraction may differ from the citation. The cited excerpt is:</p>
                  <blockquote className="mt-2 border-l-4 border-amber-400 pl-3 italic">
                    <mark>{target.excerpt}</mark>
                  </blockquote>
                </div>
              ) : (
                <p className="mb-3 text-sm text-slate-600">
                  The cited excerpt is <mark>highlighted</mark> below.
                </p>
              )}
              {text.trim() ? (
                <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-800">
                  {match ? (
                    <>
                      {text.slice(0, match.start)}
                      <mark ref={markRef}>{text.slice(match.start, match.end)}</mark>
                      {text.slice(match.end)}
                    </>
                  ) : (
                    text
                  )}
                </pre>
              ) : (
                <p className="text-sm text-slate-600">No text was extracted for this page.</p>
              )}
            </>
          ) : null}
        </div>
        <div className="border-t border-slate-200 px-4 py-3 sm:px-6">
          <button type="button" onClick={onClose} className="btn-secondary w-full sm:w-auto">
            Close
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
